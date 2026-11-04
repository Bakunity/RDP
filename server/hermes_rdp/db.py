from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import sqlite3
import struct
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    machine_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    rdp_port INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_seen INTEGER,
    telemetry_json TEXT,
    command_seq INTEGER NOT NULL DEFAULT 0,
    pending_command TEXT,
    pending_created_at INTEGER,
    last_result_json TEXT,
    ssh_key_type TEXT,
    ssh_public_key TEXT,
    slug TEXT
);

CREATE TABLE IF NOT EXISTS pair_codes (
    code_hash TEXT PRIMARY KEY,
    display_name TEXT,
    preferred_port INTEGER,
    slug TEXT,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS named_access_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER,
    revoked_at INTEGER,
    machine_name TEXT,
    route_policy TEXT NOT NULL DEFAULT 'auto',
    telemetry_json TEXT,
    updated_at INTEGER
);
"""


def now() -> int:
    return int(time.time())


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_ssh_string(blob: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(blob):
        raise ValueError("invalid SSH public key")
    length = struct.unpack(">I", blob[offset : offset + 4])[0]
    start = offset + 4
    end = start + length
    if end > len(blob):
        raise ValueError("invalid SSH public key")
    return blob[start:end], end


def normalize_ssh_public_key(value: str) -> str:
    parts = str(value).strip().split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise ValueError("only ssh-ed25519 public keys are supported")
    try:
        blob = base64.b64decode(parts[1].encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("invalid SSH public key") from exc
    algorithm, offset = _read_ssh_string(blob, 0)
    key_bytes, offset = _read_ssh_string(blob, offset)
    if algorithm != b"ssh-ed25519" or len(key_bytes) != 32 or offset != len(blob):
        raise ValueError("invalid SSH Ed25519 public key")
    return f"ssh-ed25519 {parts[1]}"


_CYRILLIC_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
})


def normalize_device_slug(value: str) -> str:
    raw = str(value or "").strip().lower().translate(_CYRILLIC_TRANSLIT)
    ascii_value = (
        unicodedata.normalize("NFKD", raw)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:48].rstrip("-")


def normalize_device_domain(value: str) -> str:
    domain = str(value or "").strip().lower().rstrip(".")
    if not domain or len(domain) > 253:
        raise ValueError("invalid device domain")
    labels = domain.split(".")
    if len(labels) < 2:
        raise ValueError("device domain must contain at least one dot")
    for label in labels:
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
        ):
            raise ValueError("invalid device domain")
    return domain


class Registry:
    def __init__(
        self,
        db_path: str | Path,
        port_start: int,
        port_end: int,
        command_timeout_seconds: int = 60,
    ):
        self.db_path = Path(db_path)
        self.port_start = int(port_start)
        self.port_end = int(port_end)
        self.command_timeout_seconds = max(1, int(command_timeout_seconds))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(devices)").fetchall()
            }
            if "ssh_key_type" not in columns:
                conn.execute("ALTER TABLE devices ADD COLUMN ssh_key_type TEXT")
            if "ssh_public_key" not in columns:
                conn.execute("ALTER TABLE devices ADD COLUMN ssh_public_key TEXT")
            if "slug" not in columns:
                conn.execute("ALTER TABLE devices ADD COLUMN slug TEXT")

            pair_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(pair_codes)").fetchall()
            }
            if "slug" not in pair_columns:
                conn.execute("ALTER TABLE pair_codes ADD COLUMN slug TEXT")

            connector_columns = {
                str(row["name"])
                for row in conn.execute(
                    "PRAGMA table_info(named_access_tokens)"
                ).fetchall()
            }
            if "machine_name" not in connector_columns:
                conn.execute(
                    "ALTER TABLE named_access_tokens "
                    "ADD COLUMN machine_name TEXT"
                )
            if "route_policy" not in connector_columns:
                conn.execute(
                    "ALTER TABLE named_access_tokens "
                    "ADD COLUMN route_policy TEXT NOT NULL DEFAULT 'auto'"
                )
            if "telemetry_json" not in connector_columns:
                conn.execute(
                    "ALTER TABLE named_access_tokens "
                    "ADD COLUMN telemetry_json TEXT"
                )
            if "updated_at" not in connector_columns:
                conn.execute(
                    "ALTER TABLE named_access_tokens "
                    "ADD COLUMN updated_at INTEGER"
                )
            conn.execute(
                "UPDATE named_access_tokens SET route_policy='auto' "
                "WHERE route_policy IS NULL OR route_policy=''"
            )

            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_active_ssh_key "
                "ON devices(ssh_public_key) "
                "WHERE revoked=0 AND ssh_public_key IS NOT NULL AND ssh_public_key<>''"
            )

            # Existing installations are upgraded in-place. Device slugs are
            # stable identifiers: display-name changes do not silently change
            # the public DNS name later.
            rows = conn.execute(
                "SELECT id,display_name,machine_name FROM devices "
                "WHERE slug IS NULL OR slug=''"
            ).fetchall()
            for row in rows:
                slug = self._allocate_slug_in_connection(
                    conn,
                    str(row["display_name"] or ""),
                    str(row["machine_name"] or ""),
                )
                conn.execute(
                    "UPDATE devices SET slug=? WHERE id=?",
                    (slug, str(row["id"])),
                )

            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_active_slug "
                "ON devices(slug) "
                "WHERE revoked=0 AND slug IS NOT NULL AND slug<>''"
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_device_domain(self) -> str:
        value = str(self.get_setting("device_domain", "") or "").strip()
        if not value:
            return ""
        return normalize_device_domain(value)

    def set_device_domain(self, value: str) -> str:
        domain = normalize_device_domain(value)
        self.set_setting("device_domain", domain)
        return domain

    def clear_device_domain(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM settings WHERE key='device_domain'")

    @staticmethod
    def normalize_route_policy(value: str) -> str:
        policy = str(value or "").strip().lower()
        if policy not in {"auto", "p2p", "relay", "lan"}:
            raise ValueError("route policy must be auto, p2p, relay, or lan")
        return policy

    @staticmethod
    def _connector_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        raw = data.get("telemetry_json")
        if raw:
            try:
                data["telemetry"] = json.loads(raw)
            except json.JSONDecodeError:
                data["telemetry"] = None
        else:
            data["telemetry"] = None
        data["route_policy"] = str(
            data.get("route_policy") or "auto"
        ).lower()
        return data

    def create_named_access_token(
        self,
        name: str = "Windows connector",
    ) -> tuple[dict[str, Any], str]:
        clean_name = str(name or "").strip()[:64] or "Windows connector"
        connector_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(40)
        timestamp = now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO named_access_tokens("
                "id,name,token_hash,created_at,updated_at,route_policy"
                ") VALUES(?,?,?,?,?,?)",
                (
                    connector_id,
                    clean_name,
                    hash_secret(token),
                    timestamp,
                    timestamp,
                    "auto",
                ),
            )
        return {
            "id": connector_id,
            "name": clean_name,
            "created_at": timestamp,
            "last_seen": None,
            "revoked_at": None,
            "machine_name": None,
            "route_policy": "auto",
            "telemetry": None,
            "updated_at": timestamp,
        }, token

    def authenticate_named_access_token(
        self,
        token: str,
    ) -> dict[str, Any] | None:
        token_hash = hash_secret(str(token or ""))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id,name,created_at,last_seen,revoked_at,"
                "machine_name,route_policy,telemetry_json,updated_at "
                "FROM named_access_tokens "
                "WHERE token_hash=? AND revoked_at IS NULL",
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            timestamp = now()
            conn.execute(
                "UPDATE named_access_tokens SET last_seen=? WHERE id=?",
                (timestamp, str(row["id"])),
            )
        data = self._connector_row(row)
        data["last_seen"] = timestamp
        return data

    def list_named_access_tokens(
        self,
        include_revoked: bool = False,
    ) -> list[dict[str, Any]]:
        where = "" if include_revoked else "WHERE revoked_at IS NULL"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,name,created_at,last_seen,revoked_at,"
                "machine_name,route_policy,telemetry_json,updated_at "
                f"FROM named_access_tokens {where} "
                "ORDER BY created_at,name"
            ).fetchall()
        return [self._connector_row(row) for row in rows]

    def get_named_access_connector(
        self,
        connector_id: str,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id,name,created_at,last_seen,revoked_at,"
                "machine_name,route_policy,telemetry_json,updated_at "
                "FROM named_access_tokens WHERE id=?",
                (connector_id,),
            ).fetchone()
        if not row:
            raise KeyError(connector_id)
        return self._connector_row(row)

    def set_named_access_route_policy(
        self,
        connector_id: str,
        policy: str,
    ) -> str:
        clean = self.normalize_route_policy(policy)
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE named_access_tokens "
                "SET route_policy=?,updated_at=? "
                "WHERE id=? AND revoked_at IS NULL",
                (clean, now(), connector_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(connector_id)
        return clean

    def update_named_access_telemetry(
        self,
        connector_id: str,
        *,
        machine_name: str,
        telemetry: dict[str, Any],
    ) -> None:
        if not isinstance(telemetry, dict):
            raise ValueError("connector telemetry object required")
        clean_machine = str(machine_name or "").strip()[:128]
        timestamp = now()
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE named_access_tokens SET "
                "machine_name=?,telemetry_json=?,last_seen=?,updated_at=? "
                "WHERE id=? AND revoked_at IS NULL",
                (
                    clean_machine or None,
                    json.dumps(
                        telemetry,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    timestamp,
                    timestamp,
                    connector_id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(connector_id)

    def revoke_named_access_token(self, connector_id: str) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE named_access_tokens SET revoked_at=? "
                "WHERE id=? AND revoked_at IS NULL",
                (now(), connector_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(connector_id)

    def create_pair_code(
        self,
        *,
        display_name: str | None = None,
        preferred_port: int | None = None,
        slug: str | None = None,
        ttl_seconds: int = 900,
    ) -> str:
        if preferred_port is not None:
            self._validate_port(preferred_port)
            if self.port_in_use(preferred_port):
                raise ValueError(f"port {preferred_port} is already assigned")
        requested_slug = normalize_device_slug(slug or "") if slug else ""
        if slug and not requested_slug:
            raise ValueError("invalid device slug")
        if requested_slug:
            with self.connect() as conn:
                if conn.execute(
                    "SELECT 1 FROM devices WHERE slug=? AND revoked=0",
                    (requested_slug,),
                ).fetchone():
                    raise ValueError(f"device slug {requested_slug} is already assigned")

        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(20):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            try:
                with self.connect() as conn:
                    conn.execute(
                        "INSERT INTO pair_codes("
                        "code_hash,display_name,preferred_port,slug,expires_at,created_at"
                        ") VALUES(?,?,?,?,?,?)",
                        (
                            hash_secret(code),
                            display_name,
                            preferred_port,
                            requested_slug or None,
                            now() + int(ttl_seconds),
                            now(),
                        ),
                    )
                return code
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("unable to allocate a unique pair code")

    def consume_pair_code(self, code: str) -> dict[str, Any]:
        code_hash = hash_secret(code.strip().upper())
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._load_pair(conn, code_hash)
            conn.execute(
                "UPDATE pair_codes SET used_at=? WHERE code_hash=?", (now(), code_hash)
            )
        return dict(row)

    def _load_pair(self, conn: sqlite3.Connection, code_hash: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM pair_codes WHERE code_hash=?", (code_hash,)
        ).fetchone()
        if not row:
            raise ValueError("invalid pair code")
        if row["used_at"] is not None:
            raise ValueError("pair code was already used")
        if int(row["expires_at"]) < now():
            raise ValueError("pair code expired")
        return row

    def _validate_port(self, port: int) -> None:
        if not self.port_start <= int(port) <= self.port_end:
            raise ValueError(
                f"port must be in range {self.port_start}-{self.port_end}"
            )

    def port_in_use(self, port: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM devices WHERE rdp_port=? AND revoked=0", (int(port),)
            ).fetchone()
        return bool(row)

    def _allocate_port_in_connection(
        self,
        conn: sqlite3.Connection,
        preferred_port: int | None = None,
    ) -> int:
        if preferred_port is not None:
            self._validate_port(preferred_port)
            row = conn.execute(
                "SELECT 1 FROM devices WHERE rdp_port=? AND revoked=0",
                (int(preferred_port),),
            ).fetchone()
            if row:
                raise ValueError(f"port {preferred_port} is already assigned")
            return int(preferred_port)
        used = {
            int(row["rdp_port"])
            for row in conn.execute(
                "SELECT rdp_port FROM devices WHERE revoked=0"
            ).fetchall()
        }
        for port in range(self.port_start, self.port_end + 1):
            if port not in used:
                return port
        raise RuntimeError("no free RDP ports")

    def allocate_port(self, preferred_port: int | None = None) -> int:
        with self.connect() as conn:
            return self._allocate_port_in_connection(conn, preferred_port)

    def _allocate_slug_in_connection(
        self,
        conn: sqlite3.Connection,
        *candidates: str,
        exclude_device_id: str | None = None,
    ) -> str:
        base = ""
        for candidate in candidates:
            base = normalize_device_slug(candidate)
            if base:
                break
        base = base or "pc"

        for suffix in range(1, 10000):
            suffix_text = "" if suffix == 1 else f"-{suffix}"
            max_base = 63 - len(suffix_text)
            candidate = f"{base[:max_base].rstrip('-')}{suffix_text}"
            params: list[Any] = [candidate]
            query = "SELECT 1 FROM devices WHERE slug=? AND revoked=0"
            if exclude_device_id is not None:
                query += " AND id<>?"
                params.append(exclude_device_id)
            if not conn.execute(query, tuple(params)).fetchone():
                return candidate
        raise RuntimeError("unable to allocate a unique device slug")

    def set_device_slug(self, device_id: str, slug: str) -> str:
        normalized = normalize_device_slug(slug)
        if not normalized:
            raise ValueError("invalid device slug")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT 1 FROM devices WHERE id=? AND revoked=0",
                (device_id,),
            ).fetchone()
            if not row:
                raise KeyError(device_id)
            if conn.execute(
                "SELECT 1 FROM devices WHERE slug=? AND id<>? AND revoked=0",
                (normalized, device_id),
            ).fetchone():
                raise ValueError(f"device slug {normalized} is already assigned")
            conn.execute(
                "UPDATE devices SET slug=?,updated_at=? WHERE id=? AND revoked=0",
                (normalized, now(), device_id),
            )
        return normalized

    def pair_device(
        self,
        *,
        code: str,
        display_name: str,
        machine_name: str,
        fingerprint: str,
        ssh_public_key: str,
    ) -> tuple[dict[str, Any], str]:
        normalized_key = normalize_ssh_public_key(ssh_public_key)
        key_type = normalized_key.split(" ", 1)[0]
        code_hash = hash_secret(code.strip().upper())
        device_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(40)
        timestamp = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pair = self._load_pair(conn, code_hash)
            port = self._allocate_port_in_connection(
                conn, pair["preferred_port"]
            )
            name = (pair["display_name"] or display_name or machine_name).strip()
            name = name[:64] or machine_name[:64] or "Windows PC"
            clean_machine_name = machine_name.strip()[:128] or "unknown"
            slug = (
                normalize_device_slug(str(pair["slug"] or ""))
                or self._allocate_slug_in_connection(
                    conn,
                    name,
                    clean_machine_name,
                )
            )
            if conn.execute(
                "SELECT 1 FROM devices WHERE slug=? AND revoked=0",
                (slug,),
            ).fetchone():
                raise ValueError(f"device slug {slug} is already assigned")
            try:
                conn.execute(
                    "INSERT INTO devices("
                    "id,display_name,machine_name,fingerprint,token_hash,rdp_port,"
                    "created_at,updated_at,ssh_key_type,ssh_public_key,slug"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        device_id,
                        name,
                        clean_machine_name,
                        fingerprint[:256],
                        hash_secret(token),
                        port,
                        timestamp,
                        timestamp,
                        key_type,
                        normalized_key,
                        slug,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("SSH key or RDP port is already assigned") from exc
            conn.execute(
                "UPDATE pair_codes SET used_at=? WHERE code_hash=?",
                (timestamp, code_hash),
            )
        return self.get_device(device_id), token

    def register_device(
        self,
        *,
        pair: dict[str, Any],
        display_name: str,
        machine_name: str,
        fingerprint: str,
        ssh_public_key: str = "",
    ) -> tuple[dict[str, Any], str]:
        normalized_key = normalize_ssh_public_key(ssh_public_key)
        device_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(40)
        name = (pair.get("display_name") or display_name or machine_name).strip()
        name = name[:64] or machine_name[:64] or "Windows PC"
        machine_name = machine_name.strip()[:128] or "unknown"
        timestamp = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            port = self._allocate_port_in_connection(
                conn,
                pair.get("preferred_port"),
            )
            requested_slug = normalize_device_slug(str(pair.get("slug") or ""))
            slug = requested_slug or self._allocate_slug_in_connection(
                conn,
                name,
                machine_name,
            )
            if conn.execute(
                "SELECT 1 FROM devices WHERE slug=? AND revoked=0",
                (slug,),
            ).fetchone():
                raise ValueError(f"device slug {slug} is already assigned")
            conn.execute(
                "INSERT INTO devices("
                "id,display_name,machine_name,fingerprint,token_hash,rdp_port,"
                "created_at,updated_at,ssh_key_type,ssh_public_key,slug"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    device_id,
                    name,
                    machine_name,
                    fingerprint[:256],
                    hash_secret(token),
                    port,
                    timestamp,
                    timestamp,
                    normalized_key.split(" ", 1)[0],
                    normalized_key,
                    slug,
                ),
            )
        return self.get_device(device_id), token

    def authenticate(self, device_id: str, token: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE id=? AND revoked=0", (device_id,)
            ).fetchone()
        if not row or not secrets.compare_digest(str(row["token_hash"]), hash_secret(token)):
            return None
        return self._device_row(row)

    def authorize_ssh_key(
        self, key_type: str, key_blob: str
    ) -> dict[str, Any] | None:
        try:
            normalized = normalize_ssh_public_key(f"{key_type} {key_blob}")
        except ValueError:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices "
                "WHERE ssh_public_key=? AND enabled=1 AND revoked=0",
                (normalized,),
            ).fetchone()
        return self._device_row(row) if row else None

    def _device_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("enabled", "revoked"):
            data[key] = bool(data[key])
        if data.get("telemetry_json"):
            try:
                data["telemetry"] = json.loads(data["telemetry_json"])
            except json.JSONDecodeError:
                data["telemetry"] = None
        else:
            data["telemetry"] = None
        if data.get("last_result_json"):
            try:
                data["last_result"] = json.loads(data["last_result_json"])
            except json.JSONDecodeError:
                data["last_result"] = None
        else:
            data["last_result"] = None
        return data

    def list_devices(self, include_revoked: bool = False) -> list[dict[str, Any]]:
        self.expire_stale_commands(self.command_timeout_seconds)
        where = "" if include_revoked else "WHERE revoked=0"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM devices {where} ORDER BY created_at, display_name"
            ).fetchall()
        return [self._device_row(row) for row in rows]

    def get_device(self, device_id: str) -> dict[str, Any]:
        self.expire_stale_commands(
            self.command_timeout_seconds,
            device_id=device_id,
        )
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if not row:
            raise KeyError(device_id)
        return self._device_row(row)

    def update_telemetry(self, device_id: str, telemetry: dict[str, Any]) -> dict[str, Any] | None:
        self.expire_stale_commands(
            self.command_timeout_seconds,
            device_id=device_id,
        )
        timestamp = now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE devices SET telemetry_json=?,last_seen=?,updated_at=? "
                "WHERE id=? AND revoked=0",
                (
                    json.dumps(telemetry, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    timestamp,
                    device_id,
                ),
            )
        return self.pending_command(device_id)

    def queue_command(self, device_id: str, action: str) -> int:
        if action not in {"on", "off", "restart", "repair", "update"}:
            raise ValueError("unsupported command")
        self.expire_stale_commands(
            self.command_timeout_seconds,
            device_id=device_id,
        )
        timestamp = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT command_seq,pending_command,enabled FROM devices "
                "WHERE id=? AND revoked=0",
                (device_id,),
            ).fetchone()
            if not row:
                raise KeyError(device_id)
            if row["pending_command"]:
                raise ValueError("previous command is still pending")
            seq = int(row["command_seq"]) + 1
            desired_enabled = (
                0
                if action == "off"
                else 1
                if action in {"on", "restart"}
                else int(row["enabled"])
            )
            conn.execute(
                "UPDATE devices SET enabled=?,command_seq=?,pending_command=?,"
                "pending_created_at=?,updated_at=? WHERE id=? AND revoked=0",
                (
                    desired_enabled,
                    seq,
                    action,
                    timestamp,
                    timestamp,
                    device_id,
                ),
            )
        return seq

    def pending_command(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT command_seq,pending_command,pending_created_at FROM devices "
                "WHERE id=? AND revoked=0",
                (device_id,),
            ).fetchone()
        if not row or not row["pending_command"]:
            return None
        return {
            "seq": int(row["command_seq"]),
            "action": str(row["pending_command"]),
            "created_at": int(row["pending_created_at"] or 0),
        }

    def expire_stale_commands(
        self,
        timeout_seconds: int,
        *,
        device_id: str | None = None,
    ) -> int:
        """Expire transient execution state while preserving desired access."""
        timeout = max(1, int(timeout_seconds))
        timestamp = now()
        cutoff = timestamp - timeout
        where = (
            "pending_command IS NOT NULL AND pending_created_at IS NOT NULL "
            "AND pending_created_at<=?"
        )
        params: list[Any] = [cutoff]
        if device_id is not None:
            where += " AND id=?"
            params.append(device_id)

        expired = 0
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id,command_seq,pending_command,pending_created_at "
                f"FROM devices WHERE {where}",
                tuple(params),
            ).fetchall()
            for row in rows:
                result = {
                    "seq": int(row["command_seq"]),
                    "action": str(row["pending_command"] or ""),
                    "ok": False,
                    "status": "timeout",
                    "message": (
                        f"Нет подтверждения от агента за {timeout} сек.; "
                        "целевое состояние сохранено"
                    ),
                    "completed_at": timestamp,
                }
                cursor = conn.execute(
                    "UPDATE devices SET pending_command=NULL,pending_created_at=NULL,"
                    "last_result_json=?,updated_at=? "
                    "WHERE id=? AND command_seq=? AND pending_command=?",
                    (
                        json.dumps(result, ensure_ascii=False),
                        timestamp,
                        str(row["id"]),
                        int(row["command_seq"]),
                        str(row["pending_command"]),
                    ),
                )
                expired += max(0, int(cursor.rowcount))
        return expired

    def complete_command(
        self, device_id: str, seq: int, ok: bool, message: str
    ) -> bool:
        timestamp = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT command_seq,pending_command FROM devices "
                "WHERE id=? AND revoked=0",
                (device_id,),
            ).fetchone()
            if (
                not row
                or int(row["command_seq"]) != int(seq)
                or not row["pending_command"]
            ):
                return False

            action = str(row["pending_command"])
            result = {
                "seq": int(seq),
                "action": action,
                "ok": bool(ok),
                "message": str(message)[:500],
                "completed_at": timestamp,
            }
            cursor = conn.execute(
                "UPDATE devices SET pending_command=NULL,pending_created_at=NULL,"
                "last_result_json=?,updated_at=? "
                "WHERE id=? AND revoked=0 AND command_seq=? AND pending_command=?",
                (
                    json.dumps(result, ensure_ascii=False),
                    timestamp,
                    device_id,
                    int(seq),
                    action,
                ),
            )
            return cursor.rowcount == 1

    def rename_device(self, device_id: str, name: str) -> None:
        clean = name.strip()[:64]
        if not clean:
            raise ValueError("name is empty")
        with self.connect() as conn:
            conn.execute(
                "UPDATE devices SET display_name=?,updated_at=? WHERE id=? AND revoked=0",
                (clean, now(), device_id),
            )

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE devices SET enabled=?,updated_at=? WHERE id=? AND revoked=0",
                (1 if enabled else 0, now(), device_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(device_id)

    def revoke_device(self, device_id: str) -> None:
        # Hard revoke: API token and SSH key disappear and the port is reusable.
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
            if cursor.rowcount == 0:
                raise KeyError(device_id)

    def cleanup(self) -> None:
        self.expire_stale_commands(self.command_timeout_seconds)
        cutoff = now() - 86400
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM pair_codes WHERE (expires_at<? OR used_at IS NOT NULL) AND created_at<?",
                (now(), cutoff),
            )