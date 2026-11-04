from __future__ import annotations

import json
import logging
import ssl
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .config import Config
from .db import Registry
from .device_certificates import get_device_certificate_target
from .tunnel import close_tunnel, endpoint_listener_state


LOG = logging.getLogger("hermes_rdp.api")
MAX_BODY = 128 * 1024
TLS_HANDSHAKE_TIMEOUT_SECONDS = 5
CLIENT_SOCKET_TIMEOUT_SECONDS = 30
CERT_PACKAGE_HELPER = "/usr/local/sbin/hermes-rdp-cert-package"
DEVICE_CERT_PACKAGE_HELPER = "/usr/local/sbin/hermes-rdp-device-cert-package"
CERT_PACKAGE_TIMEOUT_SECONDS = 30
DEVICE_CERT_TIMEOUT_SECONDS = 25
CERT_STATE_FILE = Path("/etc/hermes-rdp/trusted-rdp-cert-state.json")


def parse_helper_json(text: str) -> dict[str, Any]:
    for line in reversed(str(text or "").splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("helper returned no JSON object")


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(
        self,
        address: tuple[str, int],
        config: Config,
        registry: Registry,
        tls_context: ssl.SSLContext,
    ):
        self.config = config
        self.registry = registry
        self.tls_context = tls_context
        self.tls_handshake_timeout_seconds = TLS_HANDSHAKE_TIMEOUT_SECONDS
        self.client_socket_timeout_seconds = CLIENT_SOCKET_TIMEOUT_SECONDS
        super().__init__(address, ApiHandler)

    def process_request_thread(self, request, client_address) -> None:
        """Perform TLS in the worker thread, never in the accept loop.

        Wrapping the listening socket makes SSLSocket.accept() perform the TLS
        handshake before ThreadingHTTPServer can dispatch the connection. A
        client that opens TCP and then stalls can therefore block all new API
        traffic. Keep the listener plain TCP and wrap each accepted socket only
        after ThreadingMixIn has moved it to its own worker thread.
        """
        active_request = request
        try:
            request.settimeout(self.tls_handshake_timeout_seconds)
            active_request = self.tls_context.wrap_socket(
                request,
                server_side=True,
                do_handshake_on_connect=True,
            )
            active_request.settimeout(self.client_socket_timeout_seconds)
            self.finish_request(active_request, client_address)
        except (ssl.SSLError, TimeoutError, OSError) as exc:
            LOG.debug(
                "TLS/client connection from %s closed: %s",
                client_address[0],
                exc,
            )
        except Exception:
            self.handle_error(active_request, client_address)
        finally:
            self.shutdown_request(active_request)


class ApiHandler(BaseHTTPRequestHandler):
    server: ApiServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid request body size")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def _bearer(self) -> str:
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return ""
        return value[7:].strip()

    def _device_auth(self, device_id: str) -> dict[str, Any] | None:
        return self.server.registry.authenticate(device_id, self._bearer())

    def _named_access_auth(self) -> dict[str, Any] | None:
        return self.server.registry.authenticate_named_access_token(self._bearer())

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "hermes-rdp",
                    "version": __version__,
                    "fingerprint": self.server.config.tls_fingerprint,
                    "tunnel": "openssh",
                    "ssh_port": self.server.config.ssh_bind_port,
                },
            )
            return
        if path == "/v1/named-access/manifest":
            self._named_access_manifest()
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/v1/pair":
                self._pair()
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["v1", "devices"]:
                device_id, action = parts[2], parts[3]
                if action == "telemetry":
                    self._telemetry(device_id)
                    return
                if action == "command-result":
                    self._command_result(device_id)
                    return
                if action == "revoke-self":
                    self._revoke_self(device_id)
                    return
                if action == "rdp-certificate":
                    self._rdp_certificate(device_id)
                    return
                if action == "rdp-certificate-status":
                    self._rdp_certificate_status(device_id)
                    return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except json.JSONDecodeError:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception:
            LOG.exception("request failed")
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "internal server error"},
            )

    def _named_access_manifest(self) -> None:
        connector = self._named_access_auth()
        if not connector:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": "unauthorized"},
            )
            return

        domain = self.server.registry.get_device_domain()
        if not domain:
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "device domain is disabled"},
            )
            return

        devices = []
        for device in self.server.registry.list_devices():
            slug = str(device.get("slug") or "").strip()
            if not slug:
                continue
            devices.append(
                {
                    "id": str(device["id"]),
                    "name": str(device["display_name"]),
                    "slug": slug,
                    "hostname": f"{slug}.{domain}",
                    "rdp_port": int(device["rdp_port"]),
                    "enabled": bool(device.get("enabled", True)),
                }
            )

        self._json(
            HTTPStatus.OK,
            {
                "ok": True,
                "manifest_version": 1,
                "generated_at": int(time.time()),
                "connector": {
                    "id": str(connector["id"]),
                    "name": str(connector["name"]),
                },
                "server": {
                    "public_host": self.server.config.public_host,
                    "device_domain": domain,
                    "default_rdp_port": 3389,
                },
                "devices": devices,
            },
        )

    def _pair(self) -> None:
        body = self._read_json()
        code = str(body.get("code", "")).strip().upper()
        if len(code) != 8:
            raise ValueError("invalid pair code")
        # Validate/read server identity before consuming the one-time code.
        ssh_host_key = self.server.config.ssh_host_key
        device, device_token = self.server.registry.pair_device(
            code=code,
            display_name=str(body.get("display_name", "")),
            machine_name=str(body.get("machine_name", "")),
            fingerprint=str(body.get("fingerprint", "")),
            ssh_public_key=str(body.get("ssh_public_key", "")),
        )
        device_domain = self.server.registry.get_device_domain()
        device_slug = str(device.get("slug") or "")
        rdp_host = (
            f"{device_slug}.{device_domain}"
            if device_slug and device_domain
            else self.server.config.public_host
        )
        self._json(
            HTTPStatus.CREATED,
            {
                "ok": True,
                "device": {
                    "id": device["id"],
                    "name": device["display_name"],
                    "slug": device_slug,
                    "rdp_host": rdp_host,
                    "rdp_port": device["rdp_port"],
                    "rdp_endpoint": f"{rdp_host}:{device['rdp_port']}",
                    "token": device_token,
                },
                "api": {
                    "base_url": self.server.config.api_base_url,
                    "fingerprint": self.server.config.tls_fingerprint,
                },
                "ssh": {
                    "host": self.server.config.public_host,
                    "port": self.server.config.ssh_bind_port,
                    "user": self.server.config.ssh_user,
                    "host_key": ssh_host_key,
                    "remote_bind": "0.0.0.0",
                },
            },
        )

    def _telemetry(self, device_id: str) -> None:
        device = self._device_auth(device_id)
        if not device:
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        body = self._read_json()
        telemetry = body.get("telemetry")
        if not isinstance(telemetry, dict):
            raise ValueError("telemetry object required")

        # Expire only the transient command execution state. The durable
        # desired access flag remains untouched and is returned independently,
        # so an offline client can still converge when it comes back later.
        self.server.registry.expire_stale_commands(
            self.server.config.command_timeout_seconds,
            device_id=device_id,
        )

        # Endpoint truth belongs to the Linux server. A Windows-side TCP probe
        # can be a false positive behind VPN/TUN/proxy routing, so never trust
        # the client value for the public Hermes listener.
        telemetry = dict(telemetry)
        endpoint_state = endpoint_listener_state(int(device["rdp_port"]))
        if endpoint_state is None:
            telemetry.pop("endpoint_available", None)
            telemetry["endpoint_source"] = "unknown"
        else:
            telemetry["endpoint_available"] = endpoint_state
            telemetry["endpoint_source"] = "server_listener"

        command = self.server.registry.update_telemetry(device_id, telemetry)
        if command and command.get("action") in {"repair", "update"}:
            command = dict(command)
            command["repository_ref"] = self.server.config.client_ref
        current = self.server.registry.get_device(device_id)
        reported_client_ref = str(
            telemetry.get("client_repository_ref") or ""
        ).strip().lower()
        desired_client_ref = (
            reported_client_ref
            if self.server.config.is_client_ref_compatible(reported_client_ref)
            else self.server.config.client_ref
        )

        # Heavy telemetry is leased only for the currently opened device view.
        # Agents still poll every 3s for commands/heartbeat in background mode.
        try:
            live_until = int(self.server.registry.get_setting("live_until", "0") or 0)
        except (TypeError, ValueError):
            live_until = 0
        telemetry_live = (
            live_until > int(time.time())
            and self.server.registry.get_setting("screen", "home")
            in {"device", "device_details", "device_technical"}
            and self.server.registry.get_setting("selected_device", "") == device_id
        )

        certificate_target = get_device_certificate_target(
            self.server.registry,
            device_id,
        )
        response = {
            "ok": True,
            "command": command,
            "desired_enabled": bool(current["enabled"]),
            "desired_client_ref": desired_client_ref,
            "trusted_rdp_certificate_enabled": (
                self.server.config.trusted_rdp_certificate_enabled
            ),
            "telemetry_live": telemetry_live,
        }
        if certificate_target:
            response["desired_rdp_certificate_name"] = certificate_target["cert_name"]
            response["desired_rdp_certificate_thumbprint"] = certificate_target["thumbprint"]
        self._json(HTTPStatus.OK, response)

    def _command_result(self, device_id: str) -> None:
        if not self._device_auth(device_id):
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        body = self._read_json()
        self.server.registry.complete_command(
            device_id,
            int(body.get("seq", 0)),
            bool(body.get("ok", False)),
            str(body.get("message", "")),
        )
        self._json(HTTPStatus.OK, {"ok": True})

    def _revoke_self(self, device_id: str) -> None:
        device = self._device_auth(device_id)
        if not device:
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        self.server.registry.revoke_device(device_id)
        try:
            close_tunnel(self.server.config, int(device["rdp_port"]))
        except Exception as exc:
            LOG.warning("self-revoke tunnel close failed: %s", exc)
        self._json(HTTPStatus.OK, {"ok": True})

    def _device_certificate_mode(
        self,
        device: dict[str, Any],
    ) -> bool:
        return bool(
            self.server.registry.get_device_domain()
            and str(device.get("slug") or "").strip()
        )

    def _run_device_certificate_helper(
        self,
        device_id: str,
        mode: str,
    ) -> dict[str, Any] | None:
        try:
            result = subprocess.run(
                [
                    "sudo",
                    "-n",
                    DEVICE_CERT_PACKAGE_HELPER,
                    mode,
                    device_id,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=DEVICE_CERT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            LOG.warning(
                "device RDP certificate helper timed out for %s",
                device_id,
            )
            return None

        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1:] or ["helper failed"]
            LOG.warning(
                "device RDP certificate helper failed for %s: %s",
                device_id,
                detail[0],
            )
            return None
        try:
            return parse_helper_json(result.stdout)
        except ValueError:
            LOG.error(
                "device RDP certificate helper returned invalid JSON for %s",
                device_id,
            )
            return None

    @staticmethod
    def _validate_certificate_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        required = {"cert_name", "thumbprint", "sha256", "not_after"}
        if not required.issubset(payload):
            raise ValueError("invalid certificate metadata")
        thumbprint = str(payload["thumbprint"]).strip().upper()
        sha256 = str(payload["sha256"]).strip().upper()
        if len(thumbprint) != 40 or any(
            c not in "0123456789ABCDEF" for c in thumbprint
        ):
            raise ValueError("invalid certificate thumbprint")
        if len(sha256) != 64 or any(
            c not in "0123456789ABCDEF" for c in sha256
        ):
            raise ValueError("invalid certificate fingerprint")
        return {
            "cert_name": str(payload["cert_name"]),
            "thumbprint": thumbprint,
            "sha256": sha256,
            "not_after": str(payload["not_after"]),
            "generated_at": int(payload.get("generated_at", 0) or 0),
        }

    def _rdp_certificate_status(self, device_id: str) -> None:
        device = self._device_auth(device_id)
        if not device:
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        self._read_json()

        if self._device_certificate_mode(device):
            payload = self._run_device_certificate_helper(
                device_id,
                "--status",
            )
            if payload is None:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "error": "device certificate unavailable"},
                )
                return
            metadata = self._validate_certificate_metadata(payload)
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "enabled": True,
                    "certificate": metadata,
                },
            )
            return

        if not CERT_STATE_FILE.is_file():
            self._json(HTTPStatus.OK, {"ok": True, "enabled": False})
            return
        try:
            payload = json.loads(CERT_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOG.warning("trusted RDP certificate state is unreadable")
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "certificate state unavailable"},
            )
            return
        if not isinstance(payload, dict) or payload.get("enabled") is not True:
            self._json(HTTPStatus.OK, {"ok": True, "enabled": False})
            return

        thumbprint = str(payload.get("thumbprint", "")).strip().upper()
        if len(thumbprint) != 40 or any(c not in "0123456789ABCDEF" for c in thumbprint):
            LOG.warning("trusted RDP certificate state has invalid thumbprint")
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "certificate state unavailable"},
            )
            return
        self._json(
            HTTPStatus.OK,
            {
                "ok": True,
                "enabled": True,
                "certificate": {
                    "cert_name": str(payload.get("cert_name", "")),
                    "thumbprint": thumbprint,
                    "not_after": str(payload.get("not_after", "")),
                    "generated_at": int(payload.get("generated_at", 0) or 0),
                },
            },
        )

    def _rdp_certificate(self, device_id: str) -> None:
        device = self._device_auth(device_id)
        if not device:
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        self._read_json()

        if self._device_certificate_mode(device):
            payload = self._run_device_certificate_helper(
                device_id,
                "--package",
            )
            if payload is None:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "error": "device certificate package unavailable"},
                )
                return
        else:
            try:
                result = subprocess.run(
                    ["sudo", "-n", CERT_PACKAGE_HELPER],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=CERT_PACKAGE_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                LOG.warning("RDP certificate package helper timed out")
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "error": "certificate package unavailable"},
                )
                return
            if result.returncode != 0:
                detail = result.stderr.strip().splitlines()[-1:] or ["helper failed"]
                LOG.warning("RDP certificate package helper failed: %s", detail[0])
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "error": "certificate package unavailable"},
                )
                return
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                LOG.error("RDP certificate package helper returned invalid JSON")
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "error": "certificate package unavailable"},
                )
                return
            if not isinstance(payload, dict):
                raise ValueError("invalid certificate package")

        required = {
            "cert_name",
            "thumbprint",
            "sha256",
            "not_after",
            "password",
            "pfx_base64",
        }
        if not required.issubset(payload):
            raise ValueError("invalid certificate package")
        thumbprint = str(payload["thumbprint"]).strip().upper()
        sha256 = str(payload["sha256"]).strip().upper()
        if len(thumbprint) != 40 or any(c not in "0123456789ABCDEF" for c in thumbprint):
            raise ValueError("invalid certificate thumbprint")
        if len(sha256) != 64 or any(c not in "0123456789ABCDEF" for c in sha256):
            raise ValueError("invalid certificate fingerprint")
        if not str(payload["password"]):
            raise ValueError("invalid certificate package password")
        if len(str(payload["pfx_base64"])) < 256:
            raise ValueError("invalid certificate package payload")
        self._json(HTTPStatus.OK, {"ok": True, "certificate": payload})


def create_api_server(config: Config, registry: Registry) -> ApiServer:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config.tls_cert_file, config.tls_key_file)
    return ApiServer(("0.0.0.0", config.api_port), config, registry, context)
