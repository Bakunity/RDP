from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path


PBKDF2_ITERATIONS = 310_000
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class AdminCredentials:
    username: str
    salt: bytes
    password_hash: bytes
    iterations: int
    updated_at: int


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = PBKDF2_ITERATIONS,
) -> tuple[bytes, bytes]:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt_value = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value,
        int(iterations),
        dklen=32,
    )
    return salt_value, digest


def write_credentials(
    path: Path,
    *,
    username: str,
    password: str,
) -> None:
    clean_user = str(username or "").strip()
    if not clean_user:
        raise ValueError("username is required")
    salt, digest = hash_password(password)
    payload = {
        "version": 1,
        "username": clean_user,
        "algorithm": "pbkdf2-sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": _b64e(salt),
        "password_hash": _b64e(digest),
        "updated_at": int(time.time()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.chmod(0o640)
    temp.replace(path)


def read_credentials(path: Path) -> AdminCredentials | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(raw, dict):
        raise ValueError("invalid admin credentials")
    if str(raw.get("algorithm") or "") != "pbkdf2-sha256":
        raise ValueError("unsupported admin password algorithm")
    username = str(raw.get("username") or "").strip()
    salt = _b64d(str(raw.get("salt") or ""))
    password_hash = _b64d(str(raw.get("password_hash") or ""))
    iterations = int(raw.get("iterations") or PBKDF2_ITERATIONS)
    if not username or len(salt) < 16 or len(password_hash) != 32:
        raise ValueError("invalid admin credentials")
    return AdminCredentials(
        username=username,
        salt=salt,
        password_hash=password_hash,
        iterations=iterations,
        updated_at=int(raw.get("updated_at") or 0),
    )


def verify_password(
    path: Path,
    *,
    username: str,
    password: str,
) -> bool:
    try:
        credentials = read_credentials(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if credentials is None:
        return False
    if not hmac.compare_digest(
        str(username or "").strip(),
        credentials.username,
    ):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        credentials.salt,
        credentials.iterations,
        dklen=32,
    )
    return hmac.compare_digest(digest, credentials.password_hash)


def create_session(
    signing_secret: str,
    *,
    username: str,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> str:
    now = int(time.time())
    payload = {
        "u": str(username),
        "iat": now,
        "exp": now + max(300, int(ttl_seconds)),
        "n": secrets.token_urlsafe(12),
    }
    encoded = _b64e(
        json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_b64e(signature)}"


def verify_session(
    signing_secret: str,
    token: str,
    *,
    min_issued_at: int = 0,
) -> dict[str, object] | None:
    try:
        encoded, signature_text = str(token or "").split(".", 1)
        expected = hmac.new(
            signing_secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signature = _b64d(signature_text)
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64d(encoded).decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        if int(payload.get("iat") or 0) < int(min_issued_at):
            return None
        if not str(payload.get("u") or "").strip():
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def generate_password(length: int = 24) -> str:
    alphabet = (
        "ABCDEFGHJKLMNPQRSTUVWXYZ"
        "abcdefghijkmnopqrstuvwxyz"
        "23456789"
    )
    return "".join(secrets.choice(alphabet) for _ in range(max(16, length)))
