from __future__ import annotations

import argparse
import ipaddress
import json
import secrets
import socket
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import load_config
from .db import Registry
from .tunnel import close_tunnel, endpoint_listener_state


def parse_helper_json(text: str) -> dict:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bakunity-rdpctl")
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="manage one-time pairing codes")
    pair_sub = pair.add_subparsers(dest="pair_command", required=True)
    pair_create = pair_sub.add_parser("create")
    pair_create.add_argument("--name")
    pair_create.add_argument("--port", type=int)
    pair_create.add_argument("--slug")
    pair_create.add_argument("--ttl", type=int, default=900)

    devices = sub.add_parser("devices")
    devices_sub = devices.add_subparsers(dest="devices_command", required=True)
    devices_sub.add_parser("list")
    device_delete = devices_sub.add_parser("delete")
    device_delete.add_argument("device_id")
    device_rename = devices_sub.add_parser("rename")
    device_rename.add_argument("device_id")
    device_rename.add_argument("name")
    device_slug = devices_sub.add_parser("slug")
    device_slug.add_argument("device_id")
    device_slug.add_argument("slug")

    domain = sub.add_parser("domain", help="manage wildcard device domain")
    domain_sub = domain.add_subparsers(dest="domain_command", required=True)
    domain_set = domain_sub.add_parser("set")
    domain_set.add_argument("domain")
    domain_sub.add_parser("show")
    domain_sub.add_parser("status")
    domain_sub.add_parser("clear")

    certificates = sub.add_parser(
        "certificates",
        help="manage per-device trusted RDP certificates",
    )
    certificates_sub = certificates.add_subparsers(
        dest="certificates_command",
        required=True,
    )
    certificate_sync = certificates_sub.add_parser("sync")
    certificate_sync.add_argument("--device")
    certificates_sub.add_parser("status")

    named_access = sub.add_parser(
        "named-access",
        help="manage Windows Named Access connectors",
    )
    named_access_sub = named_access.add_subparsers(
        dest="named_access_command",
        required=True,
    )
    named_access_create = named_access_sub.add_parser("create")
    named_access_create.add_argument("--name", default="Windows connector")
    named_access_sub.add_parser("list")
    named_access_revoke = named_access_sub.add_parser("revoke")
    named_access_revoke.add_argument("connector_id")

    default_rdp = sub.add_parser(
        "default-rdp",
        help="manage the one device reachable on standard TCP 3389",
    )
    default_rdp_sub = default_rdp.add_subparsers(
        dest="default_rdp_command",
        required=True,
    )
    default_rdp_set = default_rdp_sub.add_parser("set")
    default_rdp_set.add_argument(
        "target",
        help="device id, slug, hostname, or display name",
    )
    default_rdp_sub.add_parser("show")
    default_rdp_sub.add_parser("clear")

    dashboard = sub.add_parser("dashboard")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_command", required=True)
    dashboard_sub.add_parser("reset")

    auth = sub.add_parser("authorized-key")
    auth.add_argument("username")
    auth.add_argument("key_type")
    auth.add_argument("key_blob")

    sub.add_parser("doctor")
    return parser


def resolve_device_target(registry: Registry, target: str) -> dict:
    value = str(target or "").strip().lower()
    if not value:
        raise SystemExit("device target is required")
    domain = registry.get_device_domain()
    matches = []
    for device in registry.list_devices():
        slug = str(device.get("slug") or "").strip()
        hostname = f"{slug}.{domain}" if slug and domain else ""
        candidates = {
            str(device.get("id") or "").strip().lower(),
            str(device.get("display_name") or "").strip().lower(),
            str(device.get("machine_name") or "").strip().lower(),
            slug.lower(),
            hostname.lower(),
        }
        if value in candidates:
            matches.append(device)
    if not matches:
        raise SystemExit(f"device not found: {target}")
    if len(matches) > 1:
        raise SystemExit(f"device target is ambiguous: {target}")
    return matches[0]


def systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/usr/bin/systemctl", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def main() -> None:
    args = build_parser().parse_args()
    config = load_config()
    registry = Registry(
        config.db_path,
        config.port_start,
        config.port_end,
        config.command_timeout_seconds,
    )

    if args.command == "pair" and args.pair_command == "create":
        code = registry.create_pair_code(
            display_name=args.name,
            preferred_port=args.port,
            slug=args.slug,
            ttl_seconds=args.ttl,
        )
        print(f"PAIR_CODE={code}")
        print(f"EXPIRES_IN={args.ttl}")
        print(f"SERVER={config.public_host}")
        print(f"FINGERPRINT={config.tls_fingerprint}")
        return

    if args.command == "devices" and args.devices_command == "list":
        device_domain = registry.get_device_domain()
        for device in registry.list_devices():
            age = (
                "never"
                if not device.get("last_seen")
                else str(int(time.time()) - int(device["last_seen"]))
            )
            key_state = "ssh-key=yes" if device.get("ssh_public_key") else "ssh-key=no"
            slug = str(device.get("slug") or "")
            host = (
                f"{slug}.{device_domain}"
                if slug and device_domain
                else config.public_host
            )
            print(
                f"{device['id']}\t{device['display_name']}\t{device['machine_name']}\t"
                f"{slug or '-'}\t{host}:{device['rdp_port']}\t"
                f"{key_state}\tlast_seen={age}s"
            )
        return

    if args.command == "devices" and args.devices_command == "delete":
        device = registry.get_device(args.device_id)
        registry.revoke_device(args.device_id)
        try:
            close_tunnel(config, int(device["rdp_port"]))
        except Exception as exc:
            print(f"WARNING: tunnel close failed: {exc}")
        print("OK")
        return

    if args.command == "devices" and args.devices_command == "rename":
        registry.rename_device(args.device_id, args.name)
        print("OK")
        return

    if args.command == "devices" and args.devices_command == "slug":
        slug = registry.set_device_slug(args.device_id, args.slug)
        domain = registry.get_device_domain()
        print(f"SLUG={slug}")
        if domain:
            print(f"HOST={slug}.{domain}")
        print("OK")
        return

    if args.command == "domain":
        if args.domain_command == "set":
            domain = registry.set_device_domain(args.domain)
            print(f"DEVICE_DOMAIN={domain}")
            print(f"DNS_REQUIRED=A * -> {config.public_host}")
            print("NOTE=Wildcard DNS removes per-device DNS work; RDP port remains until a gateway is enabled.")
            return

        if args.domain_command == "show":
            domain = registry.get_device_domain()
            print(f"DEVICE_DOMAIN={domain or 'disabled'}")
            return

        if args.domain_command == "clear":
            registry.clear_device_domain()
            print("DEVICE_DOMAIN=disabled")
            print("OK")
            return

        if args.domain_command == "status":
            domain = registry.get_device_domain()
            if not domain:
                print("DEVICE_DOMAIN=disabled")
                raise SystemExit(1)

            probe = f"bakunity-{secrets.token_hex(4)}.{domain}"

            def resolve(host: str) -> set[str]:
                try:
                    ipaddress.ip_address(host)
                    return {host}
                except ValueError:
                    pass
                return {
                    row[4][0]
                    for row in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
                }

            try:
                server_addresses = resolve(config.public_host)
            except OSError as exc:
                print(f"SERVER_DNS=FAIL ({exc})")
                raise SystemExit(1)

            try:
                probe_addresses = resolve(probe)
            except OSError as exc:
                print(f"DEVICE_DOMAIN={domain}")
                print(f"PROBE={probe}")
                print(f"WILDCARD_DNS=FAIL ({exc})")
                raise SystemExit(1)

            match = sorted(server_addresses & probe_addresses)
            print(f"DEVICE_DOMAIN={domain}")
            print(f"PROBE={probe}")
            print(f"SERVER_ADDRESSES={','.join(sorted(server_addresses))}")
            print(f"PROBE_ADDRESSES={','.join(sorted(probe_addresses))}")
            print(f"WILDCARD_DNS={'PASS' if match else 'MISMATCH'}")
            if not match:
                raise SystemExit(1)
            return

    if args.command == "certificates":
        helper = "/usr/local/sbin/hermes-rdp-device-cert-package"
        domain = registry.get_device_domain()
        if not domain:
            print("DEVICE_DOMAIN=disabled")
            raise SystemExit(1)

        devices = registry.list_devices()
        if getattr(args, "device", None):
            devices = [
                device
                for device in devices
                if str(device["id"]) == str(args.device)
            ]
            if not devices:
                raise SystemExit("device not found")

        if args.certificates_command == "status":
            print(f"DEVICE_DOMAIN={domain}")
            for device in devices:
                slug = str(device.get("slug") or "")
                host = f"{slug}.{domain}" if slug else "-"
                lineage = f"/etc/letsencrypt/live/bakunity-rdp-device-{device['id']}/cert.pem"
                state = "READY" if Path(lineage).is_file() else "MISSING"
                print(f"{device['id']}\t{host}\t{state}")
            return

        if args.certificates_command == "sync":
            if not Path(helper).is_file():
                raise SystemExit(f"certificate helper is missing: {helper}")
            failures = 0
            for device in devices:
                slug = str(device.get("slug") or "")
                host = f"{slug}.{domain}" if slug else "-"
                try:
                    completed = subprocess.run(
                        [helper, "--status", str(device["id"])],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    failures += 1
                    print(f"{device['id']}\t{host}\tFAIL timeout")
                    continue
                if completed.returncode != 0:
                    failures += 1
                    detail = (
                        completed.stderr.strip().splitlines()[-1:]
                        or ["helper failed"]
                    )
                    print(f"{device['id']}\t{host}\tFAIL {detail[0]}")
                    continue
                try:
                    payload = parse_helper_json(completed.stdout)
                except ValueError:
                    failures += 1
                    print(f"{device['id']}\t{host}\tFAIL invalid-json")
                    continue
                print(
                    f"{device['id']}\t{host}\tPASS "
                    f"{str(payload.get('thumbprint') or '')[:12]}"
                )
            if failures:
                raise SystemExit(1)
            return

    if args.command == "named-access":
        domain = registry.get_device_domain()
        if not domain:
            print("DEVICE_DOMAIN=disabled")
            raise SystemExit(1)

        if args.named_access_command == "create":
            connector, token = registry.create_named_access_token(args.name)
            repository_ref = config.repository_ref
            installer_url = (
                "https://raw.githubusercontent.com/bakunity/RDP/"
                f"{repository_ref}/scripts/install-named-access.ps1"
            )

            def ps_quote(value: str) -> str:
                return str(value).replace("'", "''")

            command = (
                f"$u='{ps_quote(installer_url)}'; "
                "$s=(irm $u).TrimStart([char]0xFEFF); "
                "& ([scriptblock]::Create($s)) "
                f"-ApiBaseUrl '{ps_quote(config.api_base_url)}' "
                f"-ApiFingerprint '{ps_quote(config.tls_fingerprint)}' "
                f"-AccessToken '{ps_quote(token)}' "
                f"-RepositoryRef '{ps_quote(repository_ref)}'"
            )
            print(f"CONNECTOR_ID={connector['id']}")
            print(f"CONNECTOR_NAME={connector['name']}")
            print(f"DEVICE_DOMAIN={domain}")
            print("WARNING=The next line contains a read-only secret token. Do not share it.")
            print("POWERSHELL_ADMIN_COMMAND=" + command)
            return

        if args.named_access_command == "list":
            connectors = registry.list_named_access_tokens()
            if not connectors:
                print("No active Named Access connectors.")
                return
            for connector in connectors:
                print(
                    f"{connector['id']}\t{connector['name']}\t"
                    f"created={connector['created_at']}\t"
                    f"last_seen={connector['last_seen'] or 'never'}"
                )
            return

        if args.named_access_command == "revoke":
            try:
                registry.revoke_named_access_token(args.connector_id)
            except KeyError:
                raise SystemExit("Named Access connector not found")
            print("REVOKED=PASS")
            return

    if args.command == "default-rdp":
        service = "bakunity-rdp-default.service"
        key = "default_rdp_device_id"

        if args.default_rdp_command == "set":
            if hasattr(args, "target"):
                device = resolve_device_target(registry, args.target)
            else:
                raise SystemExit("device target is required")

            active = systemctl("is-active", "--quiet", service).returncode == 0
            if endpoint_listener_state(3389) and not active:
                raise SystemExit(
                    "TCP 3389 is already used by another listener; "
                    "default RDP was not changed"
                )

            previous = str(registry.get_setting(key, "") or "")
            registry.set_setting(key, str(device["id"]))
            enabled = systemctl("enable", "--now", service)
            if enabled.returncode != 0:
                registry.set_setting(key, previous)
                detail = (enabled.stderr or enabled.stdout or "").strip()
                raise SystemExit(
                    detail or "failed to start default RDP service"
                )

            domain = registry.get_device_domain()
            slug = str(device.get("slug") or "").strip()
            host = f"{slug}.{domain}" if slug and domain else config.public_host
            print(f"DEFAULT_RDP={host}")
            print(f"TARGET={device['display_name']}")
            print(f"TARGET_PORT={device['rdp_port']}")
            print("LISTEN_PORT=3389")
            print("OK")
            return

        if args.default_rdp_command == "show":
            device_id = str(registry.get_setting(key, "") or "").strip()
            if not device_id:
                print("DEFAULT_RDP=disabled")
                return
            try:
                device = registry.get_device(device_id)
            except KeyError:
                print("DEFAULT_RDP=broken")
                print(f"DEVICE_ID={device_id}")
                raise SystemExit(1)
            domain = registry.get_device_domain()
            slug = str(device.get("slug") or "").strip()
            host = f"{slug}.{domain}" if slug and domain else config.public_host
            active = systemctl("is-active", "--quiet", service).returncode == 0
            print(f"DEFAULT_RDP={host}")
            print(f"TARGET={device['display_name']}")
            print(f"TARGET_PORT={device['rdp_port']}")
            print(f"SERVICE={'active' if active else 'inactive'}")
            print(f"LISTENER={'yes' if endpoint_listener_state(3389) else 'no'}")
            if not active or not endpoint_listener_state(3389):
                raise SystemExit(1)
            return

        if args.default_rdp_command == "clear":
            registry.set_setting(key, "")
            stopped = systemctl("disable", "--now", service)
            if stopped.returncode != 0:
                detail = (stopped.stderr or stopped.stdout or "").strip()
                raise SystemExit(detail or "failed to stop default RDP service")
            print("DEFAULT_RDP=disabled")
            print("OK")
            return

    if args.command == "dashboard" and args.dashboard_command == "reset":
        registry.set_setting("dashboard_message_id", "")
        registry.set_setting("screen", "home")
        registry.set_setting("selected_device", "")
        print("Dashboard state reset. Send /start to the bot.")
        return

    if args.command == "authorized-key":
        device = registry.authorize_ssh_key(args.key_type, args.key_blob)
        if device and args.username == config.ssh_user:
            port = int(device["rdp_port"])
            options = (
                "no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc,"
                f'permitlisten="0.0.0.0:{port}"'
            )
            print(
                f"{options} {device['ssh_public_key']} "
                f"hermes-rdp-{device['id']}"
            )
        return

    if args.command == "doctor":
        errors = 0
        print(f"config: OK ({config.public_host})")
        print(f"server-ref: {config.repository_ref}")
        print(f"client-ref: {config.client_ref}")
        print(
            "client-compatible-refs: "
            + ",".join(config.compatible_client_refs)
        )
        print(f"database: OK ({config.db_path})")
        device_domain = registry.get_device_domain()
        print(f"device-domain: {device_domain or 'disabled'}")
        default_device_id = str(
            registry.get_setting("default_rdp_device_id", "") or ""
        ).strip()
        if default_device_id:
            try:
                default_device = registry.get_device(default_device_id)
                default_slug = str(default_device.get("slug") or "").strip()
                default_host = (
                    f"{default_slug}.{device_domain}"
                    if default_slug and device_domain
                    else config.public_host
                )
                if endpoint_listener_state(3389):
                    print(
                        "default-rdp: LISTEN 3389 -> "
                        f"{default_host}:{default_device['rdp_port']}"
                    )
                else:
                    errors += 1
                    print(
                        "default-rdp: FAIL 3389 -> "
                        f"{default_host}:{default_device['rdp_port']}"
                    )
            except KeyError:
                errors += 1
                print(f"default-rdp: FAIL missing-device {default_device_id}")
        else:
            print("default-rdp: disabled")
        try:
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(
                f"https://127.0.0.1:{config.api_port}/healthz",
                context=context,
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            print(f"api: OK ({payload.get('version')}, {payload.get('tunnel')})")
        except Exception as exc:
            errors += 1
            print(f"api: FAIL ({exc})")
        for port, name in [
            (config.ssh_bind_port, "ssh-tunnel"),
            (config.api_port, "api"),
        ]:
            sock = socket.socket()
            sock.settimeout(2)
            try:
                sock.connect(("127.0.0.1", port))
                print(f"{name}: LISTEN {port}")
            except OSError as exc:
                errors += 1
                print(f"{name}: FAIL {port} ({exc})")
            finally:
                sock.close()
        try:
            completed = subprocess.run(
                ["/usr/sbin/sshd", "-t", "-f", "/etc/hermes-rdp/sshd_config"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed.returncode:
                raise RuntimeError((completed.stderr or completed.stdout).strip())
            print("ssh-config: OK")
        except Exception as exc:
            errors += 1
            print(f"ssh-config: FAIL ({exc})")
        if errors:
            raise SystemExit(1)
        return


if __name__ == "__main__":
    main()
