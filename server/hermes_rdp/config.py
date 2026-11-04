from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG = Path("/etc/hermes-rdp/config.json")


@dataclass(frozen=True)
class Config:
    public_host: str
    api_port: int
    ssh_bind_port: int
    ssh_user: str
    port_start: int
    port_end: int
    data_dir: Path
    db_path: Path
    telegram_token_file: Path
    telegram_chat_id: str
    tls_cert_file: Path
    tls_key_file: Path
    tls_fingerprint_file: Path
    ssh_host_key_file: Path
    client_installer_url: str
    repository_ref: str
    close_tunnel_helper: Path
    client_repository_ref: str = ""
    online_after_seconds: int = 15
    pair_ttl_seconds: int = 900
    command_timeout_seconds: int = 60
    trusted_rdp_certificate_enabled: bool = False

    @property
    def client_ref(self) -> str:
        return self.client_repository_ref or self.repository_ref

    @property
    def api_base_url(self) -> str:
        return f"https://{self.public_host}:{self.api_port}"

    def read_secret(self, path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    @property
    def telegram_token(self) -> str:
        return self.read_secret(self.telegram_token_file)

    @property
    def tls_fingerprint(self) -> str:
        return self.read_secret(self.tls_fingerprint_file).upper()

    @property
    def ssh_host_key(self) -> str:
        parts = self.read_secret(self.ssh_host_key_file).split()
        if len(parts) < 2:
            raise ValueError("invalid SSH host public key")
        return f"{parts[0]} {parts[1]}"


def load_config(path: str | Path = DEFAULT_CONFIG) -> Config:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data_dir = Path(data.get("data_dir", "/var/lib/hermes-rdp"))
    return Config(
        public_host=str(data["public_host"]),
        api_port=int(data.get("api_port", 7443)),
        ssh_bind_port=int(data.get("ssh_bind_port", data.get("frp_bind_port", 7000))),
        ssh_user=str(data.get("ssh_user", "hermes-tunnel")),
        port_start=int(data.get("port_start", 53389)),
        port_end=int(data.get("port_end", 53420)),
        data_dir=data_dir,
        db_path=Path(data.get("db_path", data_dir / "state.sqlite3")),
        telegram_token_file=Path(
            data.get("telegram_token_file", "/etc/hermes-rdp/telegram-token")
        ),
        telegram_chat_id=str(data["telegram_chat_id"]),
        tls_cert_file=Path(data.get("tls_cert_file", "/etc/hermes-rdp/tls/api.crt")),
        tls_key_file=Path(data.get("tls_key_file", "/etc/hermes-rdp/tls/api.key")),
        tls_fingerprint_file=Path(
            data.get("tls_fingerprint_file", "/etc/hermes-rdp/tls/api.sha256")
        ),
        ssh_host_key_file=Path(
            data.get("ssh_host_key_file", "/etc/hermes-rdp/ssh-host-key.pub")
        ),
        client_installer_url=str(
            data.get(
                "client_installer_url",
                "https://raw.githubusercontent.com/bakunity/RDP/main/scripts/install-client.ps1",
            )
        ),
        repository_ref=str(data.get("repository_ref", "main")),
        close_tunnel_helper=Path(
            data.get(
                "close_tunnel_helper",
                "/usr/local/sbin/hermes-rdp-close-tunnel",
            )
        ),
        client_repository_ref=str(
            data.get(
                "client_repository_ref",
                data.get("repository_ref", "main"),
            )
        ),
        online_after_seconds=int(data.get("online_after_seconds", 15)),
        pair_ttl_seconds=int(data.get("pair_ttl_seconds", 900)),
        command_timeout_seconds=max(5, int(data.get("command_timeout_seconds", 60))),
        trusted_rdp_certificate_enabled=bool(
            (data.get("trusted_rdp_certificate") or {}).get("enabled", False)
        ),
    )
