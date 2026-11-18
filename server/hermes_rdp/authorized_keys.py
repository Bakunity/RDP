from __future__ import annotations

import sys

from .config import load_config
from .db import Registry


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(1)
    username, key_type, key_blob = sys.argv[1:]
    config = load_config()
    if username != config.ssh_user:
        raise SystemExit(0)
    registry = Registry(config.db_path, config.port_start, config.port_end)
    device = registry.authorize_ssh_key(key_type, key_blob)
    if not device:
        raise SystemExit(0)
    port = int(device["rdp_port"])
    access_port = port + 1000
    options = (
        "no-agent-forwarding,"
        "no-X11-forwarding,"
        "no-pty,"
        "no-user-rc,"
        f'permitlisten="0.0.0.0:{port}",'
        f'permitlisten="127.0.0.1:{access_port}"'
    )
    public_key = str(device["ssh_public_key"])
    print(f"{options} {public_key} hermes-rdp-{device['id']}")


if __name__ == "__main__":
    main()
