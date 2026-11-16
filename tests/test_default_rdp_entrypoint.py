from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_rdp.default_rdp import _read_target


ROOT = Path(__file__).resolve().parents[1]


class DefaultRdpEntrypointTests(unittest.TestCase):
    def test_read_target_uses_enabled_configured_device(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "state.sqlite3"
            connection = sqlite3.connect(db)
            try:
                connection.executescript(
                    """
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE devices (
                        id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        rdp_port INTEGER NOT NULL,
                        enabled INTEGER NOT NULL,
                        revoked INTEGER NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?)",
                    ("default_rdp_device_id", "dev1"),
                )
                connection.execute(
                    "INSERT INTO devices(id,display_name,rdp_port,enabled,revoked) "
                    "VALUES(?,?,?,?,?)",
                    ("dev1", "MIPC", 53389, 1, 0),
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(_read_target(db), ("MIPC", 53389))

    def test_read_target_fails_closed_for_disabled_device(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "state.sqlite3"
            connection = sqlite3.connect(db)
            try:
                connection.executescript(
                    """
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE devices (
                        id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        rdp_port INTEGER NOT NULL,
                        enabled INTEGER NOT NULL,
                        revoked INTEGER NOT NULL
                    );
                    INSERT INTO settings(key,value)
                    VALUES('default_rdp_device_id','dev1');
                    INSERT INTO devices(id,display_name,rdp_port,enabled,revoked)
                    VALUES('dev1','MIPC',53389,0,0);
                    """
                )
                connection.commit()
            finally:
                connection.close()

            self.assertIsNone(_read_target(db))

    def test_cli_manages_one_standard_3389_device(self) -> None:
        cli = (ROOT / "server/hermes_rdp/cli.py").read_text(encoding="utf-8")
        self.assertIn('"default-rdp"', cli)
        self.assertIn('"default_rdp_device_id"', cli)
        self.assertIn("endpoint_listener_state(3389)", cli)
        self.assertIn('"enable", "--now", service', cli)
        self.assertIn('"disable", "--now", service', cli)
        self.assertIn("LISTEN_PORT=3389", cli)

    def test_server_install_and_update_manage_default_entrypoint(self) -> None:
        install = (ROOT / "scripts/install-server.sh").read_text(encoding="utf-8")
        update = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        unit = "bakunity-rdp-default.service"
        self.assertIn(unit, install)
        self.assertIn('ufw allow "3389/tcp"', install)
        self.assertIn(unit, update)
        self.assertIn('ufw allow "3389/tcp"', update)
        self.assertIn("DEFAULT_RDP_CONFIGURED", update)
        self.assertIn(
            "systemctl enable --now bakunity-rdp-default.service",
            update,
        )
        self.assertIn(
            "restore_optional_file /etc/systemd/system/bakunity-rdp-default.service",
            update,
        )

    def test_doctor_checks_default_service_and_reports_device_health(self) -> None:
        cli = (ROOT / "server/hermes_rdp/cli.py").read_text(encoding="utf-8")
        self.assertIn('systemctl("is-active", "--quiet", default_service)', cli)
        self.assertIn("default-rdp: OK 3389", cli)
        self.assertIn("default-rdp: FAIL", cli)
        self.assertIn("endpoint_listener_state(port)", cli)
        self.assertIn("client_state", cli)
        self.assertIn("cert_state", cli)
        self.assertIn("tunnel=", cli)
        self.assertIn("ssh_tunnel_running", cli)
        self.assertIn("ssh_process_count", cli)
        self.assertIn("access=", cli)
        self.assertIn("pending=", cli)
        self.assertIn("last_command=", cli)

    def test_cli_can_queue_one_device_fallback_restart(self) -> None:
        cli = (ROOT / "server/hermes_rdp/cli.py").read_text(encoding="utf-8")
        self.assertIn('devices_sub.add_parser(\n        "restart"', cli)
        self.assertIn('args.devices_command == "restart"', cli)
        self.assertIn('resolve_device_target(registry, args.target)', cli)
        self.assertIn('registry.queue_command(str(device["id"]), "restart")', cli)
        self.assertIn('print("QUEUED=PASS")', cli)

    def test_systemd_service_runs_unprivileged_proxy(self) -> None:
        service = (
            ROOT / "server/systemd/bakunity-rdp-default.service"
        ).read_text(encoding="utf-8")
        self.assertIn("User=hermes-rdp", service)
        self.assertIn("Group=hermes-rdp", service)
        self.assertIn("-m hermes_rdp.default_rdp", service)
        self.assertIn("NoNewPrivileges=true", service)


if __name__ == "__main__":
    unittest.main()
