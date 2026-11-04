from __future__ import annotations

import logging
import select
import socket
import socketserver
import sqlite3
from pathlib import Path

from .config import load_config


LOG = logging.getLogger("hermes_rdp.default_rdp")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 3389
BUFFER_SIZE = 64 * 1024


def _read_target(db_path: Path) -> tuple[str, int] | None:
    connection = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    try:
        setting = connection.execute(
            "SELECT value FROM settings WHERE key='default_rdp_device_id'"
        ).fetchone()
        device_id = str(setting["value"] or "").strip() if setting else ""
        if not device_id:
            return None
        row = connection.execute(
            "SELECT display_name,rdp_port,enabled "
            "FROM devices WHERE id=? AND revoked=0",
            (device_id,),
        ).fetchone()
        if not row or not bool(row["enabled"]):
            return None
        return str(row["display_name"]), int(row["rdp_port"])
    finally:
        connection.close()


class DefaultRdpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        target = _read_target(self.server.db_path)
        if target is None:
            return
        name, port = target
        try:
            upstream = socket.create_connection(("127.0.0.1", port), timeout=5)
        except OSError as exc:
            LOG.info("default RDP target %s:%s unavailable: %s", name, port, exc)
            return

        client = self.request
        client.settimeout(None)
        upstream.settimeout(None)
        try:
            peers = {client: upstream, upstream: client}
            sockets = [client, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 60)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(BUFFER_SIZE)
                    if not data:
                        return
                    peers[source].sendall(data)
        except (ConnectionError, OSError):
            return
        finally:
            try:
                upstream.close()
            except OSError:
                pass


class DefaultRdpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], db_path: Path):
        self.db_path = db_path
        super().__init__(address, DefaultRdpHandler)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    server = DefaultRdpServer((LISTEN_HOST, LISTEN_PORT), config.db_path)
    LOG.info("default RDP listener started on %s:%s", LISTEN_HOST, LISTEN_PORT)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
