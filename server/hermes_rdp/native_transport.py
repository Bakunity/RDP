from __future__ import annotations

import json
import re
import secrets
import urllib.error
import urllib.request
from typing import Any


HOST_STATE_PREFIX = "native_transport_host:"
HOST_SECRET_PREFIX = "native_transport_secret:"
PEER_ID_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{20,96}$")


def native_transport_enabled(registry: Any) -> bool:
    return str(
        registry.get_setting("native_transport_enabled", "0") or "0"
    ) == "1"


def native_transport_relay_addr(registry: Any) -> str:
    return str(
        registry.get_setting("native_transport_relay_addr", "") or ""
    ).strip()


def get_or_create_host_secret(registry: Any, device_id: str) -> str:
    key = f"{HOST_SECRET_PREFIX}{device_id}"
    value = str(registry.get_setting(key, "") or "").strip()
    if value:
        return value
    value = secrets.token_urlsafe(32)
    registry.set_setting(key, value)
    return value


def get_native_transport_host(
    registry: Any,
    device_id: str,
) -> dict[str, Any]:
    raw = str(
        registry.get_setting(f"{HOST_STATE_PREFIX}{device_id}", "") or ""
    )
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _clean_peer_id(value: Any) -> str:
    peer_id = str(value or "").strip()
    if not PEER_ID_RE.fullmatch(peer_id):
        return ""
    return peer_id


def normalize_native_transport_host(
    payload: dict[str, Any],
) -> dict[str, Any]:
    path = str(payload.get("path") or "").strip().lower()
    if path not in {
        "idle",
        "direct",
        "relay",
        "connecting",
        "unavailable",
    }:
        path = "idle"

    return {
        "captured_at": int(payload.get("captured_at") or 0),
        "installed": bool(payload.get("installed")),
        "online": bool(payload.get("online")),
        "peer_id": _clean_peer_id(payload.get("peer_id")),
        "relay_connected": bool(payload.get("relay_connected")),
        "path": path,
        "version": str(payload.get("version") or "")[:64],
    }


def authorize_native_transport_peer(peer_id: Any) -> bool:
    clean = _clean_peer_id(peer_id)
    if not clean:
        return False
    body = json.dumps(
        {"peer_id": clean},
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:7445/allow",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        return False
    return bool(isinstance(payload, dict) and payload.get("ok") is True)


def set_native_transport_host(
    registry: Any,
    device_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    state = normalize_native_transport_host(payload)
    if state["online"] and not state["peer_id"]:
        state["online"] = False
    registry.set_setting(
        f"{HOST_STATE_PREFIX}{device_id}",
        json.dumps(
            state,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    if state["online"] and state["peer_id"]:
        authorize_native_transport_peer(state["peer_id"])
    return state


def native_transport_host_manifest(
    registry: Any,
    device_id: str,
) -> dict[str, Any]:
    state = get_native_transport_host(registry, device_id)
    peer_id = _clean_peer_id(state.get("peer_id"))
    enabled = (
        native_transport_enabled(registry)
        and bool(peer_id)
        and bool(state.get("online"))
    )
    return {
        "available": enabled,
        "peer_id": peer_id,
        "shared_secret": (
            get_or_create_host_secret(registry, device_id)
            if enabled
            else ""
        ),
        "path": str(state.get("path") or "idle"),
    }


def native_transport_bootstrap(
    registry: Any,
    device_id: str,
) -> dict[str, Any] | None:
    if not native_transport_enabled(registry):
        return None
    relay_addr = native_transport_relay_addr(registry)
    if not relay_addr:
        raise RuntimeError("Bakunity Transport relay is unavailable")
    return {
        "relay_addr": relay_addr,
        "shared_secret": get_or_create_host_secret(
            registry,
            device_id,
        ),
    }
