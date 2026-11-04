from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerUpdateBehaviorTests(unittest.TestCase):
    def test_install_server_restarts_openssh_services(self) -> None:
        text = (ROOT / "scripts/install-server.sh").read_text(encoding="utf-8")
        self.assertIn(
            "systemctl enable hermes-rdp-sshd.service hermes-rdp.service",
            text,
        )
        self.assertIn(
            "systemctl restart hermes-rdp-sshd.service hermes-rdp.service",
            text,
        )
        self.assertNotIn("systemctl enable --now", text)

    def test_update_server_resolves_requested_ref_to_immutable_sha(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("https://api.github.com/repos/$REPO/commits/$REF_ENCODED", text)
        self.assertIn("https://codeload.github.com/$REPO/tar.gz/$RESOLVED_SHA", text)
        self.assertNotIn("https://codeload.github.com/$REPO/tar.gz/$REF", text)
        self.assertIn('data["repository_ref"] = resolved_sha', text)
        self.assertIn('data["repository_requested_ref"] = requested_ref', text)
        self.assertIn("f\"{resolved_sha}/scripts/install-client.ps1\"", text)

    def test_update_server_creates_consistent_database_backup(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("$BACKUP/var/lib/hermes-rdp/state.sqlite3", text)
        self.assertIn("source.backup(destination)", text)
        self.assertIn('destination.execute("PRAGMA quick_check")', text)
        self.assertIn("update-metadata.json", text)
        self.assertIn('"resolved_sha": resolved_sha', text)

    def test_update_server_has_health_gated_automatic_rollback(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("ROLLBACK_ARMED=1", text)
        self.assertIn("rollback_update", text)
        self.assertIn("trap 'rollback_update", text)
        self.assertIn("wait_health", text)
        self.assertIn("python3 -m hermes_rdp.cli doctor", text)
        self.assertIn('connection.execute("PRAGMA quick_check")', text)
        self.assertIn("ROLLBACK=PASS", text)
        self.assertIn("ROLLBACK=FAIL", text)

    def test_update_server_installs_cli_aliases_transactionally(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        for wrapper in (
            "/usr/local/bin/hermes-rdpctl",
            "/usr/local/bin/bakunity-rdpctl",
        ):
            self.assertIn(wrapper, text)
            self.assertIn(f"restore_optional_file {wrapper}", text)
            self.assertIn(f"{wrapper} doctor >/dev/null", text)
        self.assertGreaterEqual(
            text.count("export PYTHONPATH=/opt/hermes-rdp/app"),
            2,
        )

    def test_plain_updater_refuses_major_frp_migration(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("This server still uses FRP.", text)
        self.assertIn("install-server.sh with --migrate", text)


if __name__ == "__main__":
    unittest.main()
