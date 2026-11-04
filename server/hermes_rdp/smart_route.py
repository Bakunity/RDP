from __future__ import annotations

import ipaddress
import json
import subprocess
from typing import Any


MESH_KEY_HELPER = "/usr/local/sbin/bakunity-rdp-mesh-key"
MESH_KEY_TIMEOUT_SECONDS = 15
HOST_STATE_PREFIX = "smart_route_host:"


def mesh_enabled(registry: Any) -> bool:
    return str(registry.get_setting("smart_route_enabled", "0") or "0") == "1"


def mesh_control_url(registry: Any) -> str:
    return str(registry.get_setting("smart_route_control_url", "") or "").strip()


def get_host_smart_route(registry: Any, device_id: str) -> dict[str, Any]:
    raw = str(registry.get_setting(f"{HOST_STATE_PREFIX}{device_id}", "") or "")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _valid_lan_ipv4(value: Any) -> str | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if address.version != 4:
        return None
    private_ranges = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    if not any(address in network for network in private_ranges):
        return None
    return str(address)


def _valid_mesh_ipv4(value: Any) -> str:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return ""
    if address.version != 4 or address not in ipaddress.ip_network("100.64.0.0/10"):
        return ""
    return str(address)


def normalize_host_smart_route(payload: dict[str, Any]) -> dict[str, Any]:
    lan = []
    seen = set()
    for item in payload.get("lan_ipv4") or []:
        value = _valid_lan_ipv4(item)
        if value and value not in seen:
            seen.add(value)
            lan.append(value)
        if len(lan) >= 16:
            break

    mesh_ipv4 = _valid_mesh_ipv4(payload.get("mesh_ipv4"))
    return {
        "captured_at": int(payload.get("captured_at") or 0),
        "lan_ipv4": lan,
        "mesh_installed": bool(payload.get("mesh_installed")),
        "mesh_online": bool(payload.get("mesh_online")) and bool(mesh_ipv4),
        "mesh_ipv4": mesh_ipv4,
        "mesh_conflict": bool(payload.get("mesh_conflict")),
        "mesh_version": str(payload.get("mesh_version") or "")[:64],
    }


def set_host_smart_route(
    registry: Any,
    device_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    state = normalize_host_smart_route(payload)
    registry.set_setting(
        f"{HOST_STATE_PREFIX}{device_id}",
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
    )
    return state


def create_mesh_bootstrap(registry: Any, role: str) -> dict[str, str] | None:
    if not mesh_enabled(registry):
        return None
    control_url = mesh_control_url(registry)
    if not control_url.startswith("https://"):
        raise RuntimeError("Smart Route mesh control URL is unavailable")
    if role not in {"host", "connector"}:
        raise ValueError("invalid mesh role")

    completed = subprocess.run(
        ["/usr/bin/sudo", "-n", MESH_KEY_HELPER, role],
        check=False,
        capture_output=True,
        text=True,
        timeout=MESH_KEY_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or ["mesh key helper failed"]
        raise RuntimeError(detail[0])
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("mesh key helper returned invalid JSON") from exc
    key = str(payload.get("auth_key") or "")
    if len(key) < 20 or any(character.isspace() for character in key):
        raise RuntimeError("mesh key helper returned invalid auth key")
    return {
        "control_url": control_url,
        "auth_key": key,
    }
