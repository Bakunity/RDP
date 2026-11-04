from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_rdp.db import Registry
from hermes_rdp.tunnel import _proc_net_has_listener


ROOT = Path(__file__).resolve().parents[1]


class OpenSshMigrationSafetyTests(unittest.TestCase):
    def test_legacy_database_adds_ssh_columns_before_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE devices (
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
                        last_result_json TEXT
                    );
                    CREATE TABLE pair_codes (
                        code_hash TEXT PRIMARY KEY,
                        display_name TEXT,
                        preferred_port INTEGER,
                        expires_at INTEGER NOT NULL,
                        created_at INTEGER NOT NULL,
                        used_at INTEGER
                    );
                    CREATE TABLE settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )
            registry = Registry(database, 53389, 53420)
            with registry.connect() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(devices)"
                    ).fetchall()
                }
                indexes = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA index_list(devices)"
                    ).fetchall()
                }
            self.assertIn("ssh_key_type", columns)
            self.assertIn("ssh_public_key", columns)
            self.assertIn("idx_devices_active_ssh_key", indexes)

    def test_windows_key_generation_preserves_empty_passphrase_argument(self) -> None:
        installer = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("Start-Process", installer)
        self.assertIn("'-N'", installer)
        self.assertIn("'\"\"'", installer)
        self.assertNotIn("-N ''", installer)

    def test_tunnel_close_helper_matches_sshd_executable(self) -> None:
        installer = (ROOT / "scripts/install-server.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('readlink -f "/proc/$PID/exe"', installer)
        self.assertIn('"$EXE" == /usr/sbin/sshd', installer)
        self.assertNotIn('COMMAND="$(tr', installer)

    def test_proc_net_listener_parser_uses_listen_state(self) -> None:
        proc_net = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:D08D 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 1
   1: 0100007F:D08E 0100007F:1234 01 00000000:00000000 00:00000000 00000000 0 0 2
"""
        self.assertTrue(_proc_net_has_listener(proc_net, 53389))
        self.assertFalse(_proc_net_has_listener(proc_net, 53390))

    def test_api_overwrites_client_endpoint_with_server_listener(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn("endpoint_listener_state", api)
        self.assertIn('telemetry["endpoint_available"] = endpoint_state', api)
        self.assertIn('telemetry["endpoint_source"] = "server_listener"', api)


if __name__ == "__main__":
    unittest.main()
