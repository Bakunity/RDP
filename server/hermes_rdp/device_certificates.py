from __future__ import annotations

import json
import subprocess
from typing import Any

from .config import Config
from .db import Registry


DEVICE_CERT_PACKAGE_HELPER = "/usr/local/sbin/hermes-rdp-device-cert-package"
DEVICE_CERT_TIMEOUT_SECONDS = 90
TARGET_KEY_PREFIX = "device_certificate_target:"


def _parse_helper_json(text: str) -> dict[str, Any]:
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
    raise ValueError("certificate helper returned no JSON object")


def _target_key(device_id: str) -> str:
    return f"{TARGET_KEY_PREFIX}{device_id}"


def get_device_certificate_target(
    registry: Registry,
    device_id: str,
) -> dict[str, str] | None:
    raw = str(registry.get_setting(_target_key(device_id), "") or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    cert_name = str(payload.get("cert_name") or "").strip().lower()
    thumbprint = str(payload.get("thumbprint") or "").strip().upper()
    if not cert_name:
        return None
    if len(thumbprint) != 40 or any(c not in "0123456789ABCDEF" for c in thumbprint):
        return None
    return {
        "cert_name": cert_name,
        "thumbprint": thumbprint,
        "not_after": str(payload.get("not_after") or ""),
    }


def ensure_device_certificate_target(
    config: Config,
    registry: Registry,
    device_id: str,
) -> dict[str, str] | None:
    domain = str(registry.get_device_domain() or "").strip().lower().rstrip(".")
    device = registry.get_device(device_id)
    slug = str(device.get("slug") or "").strip().lower()
    if not config.trusted_rdp_certificate_enabled or not domain or not slug:
        return None

    expected_name = f"{slug}.{domain}"
    try:
        completed = subprocess.run(
            [
                "/usr/bin/sudo",
                "-n",
                DEVICE_CERT_PACKAGE_HELPER,
                "--status",
                device_id,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=DEVICE_CERT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("certificate issuance timed out") from exc

    if completed.returncode != 0:
        detail = (
            completed.stderr.strip().splitlines()[-1:]
            or completed.stdout.strip().splitlines()[-1:]
            or ["certificate helper failed"]
        )
        raise RuntimeError(detail[0])

    payload = _parse_helper_json(completed.stdout)
    cert_name = str(payload.get("cert_name") or "").strip().lower()
    thumbprint = str(payload.get("thumbprint") or "").strip().upper()
    if cert_name != expected_name:
        raise RuntimeError(
            f"certificate name mismatch: expected {expected_name}, got {cert_name or '-'}"
        )
    if len(thumbprint) != 40 or any(c not in "0123456789ABCDEF" for c in thumbprint):
        raise RuntimeError("certificate helper returned invalid thumbprint")

    target = {
        "cert_name": cert_name,
        "thumbprint": thumbprint,
        "not_after": str(payload.get("not_after") or ""),
    }
    registry.set_setting(
        _target_key(device_id),
        json.dumps(target, ensure_ascii=False, separators=(",", ":")),
    )
    return target


def set_device_slug_with_certificate(
    config: Config,
    registry: Registry,
    device_id: str,
    slug: str,
) -> tuple[str, dict[str, str] | None]:
    before = registry.get_device(device_id)
    previous_slug = str(before.get("slug") or "").strip()
    normalized = registry.set_device_slug(device_id, slug)
    if normalized == previous_slug:
        return normalized, ensure_device_certificate_target(
            config,
            registry,
            device_id,
        )

    try:
        target = ensure_device_certificate_target(
            config,
            registry,
            device_id,
        )
    except Exception:
        if previous_slug:
            registry.set_device_slug(device_id, previous_slug)
        raise

    return normalized, target
