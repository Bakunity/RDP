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
        self.assertIn("f\"{client_ref}/scripts/install-client.ps1\"", text)

    def test_update_server_defines_previous_client_ref_before_metadata(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        assignment = 'PREVIOUS_CLIENT_REF="$CONFIG_CLIENT_REF"'
        metadata_use = '"$PREVIOUS_CLIENT_REF"'
        self.assertIn(assignment, text)
        self.assertIn(metadata_use, text)
        self.assertLess(text.index(assignment), text.index(metadata_use))

    def test_server_update_preserves_equivalent_client_refs(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("client_bundle_hash()", text)
        self.assertIn("TELEMETRY_CLIENT_REFS", text)
        self.assertIn('telemetry.get("client_repository_ref")', text)
        self.assertIn("CANDIDATE_CLIENT_REFS", text)
        self.assertIn("COMPATIBLE_CLIENT_REFS", text)
        self.assertIn("TARGET_CLIENT_HASH", text)
        self.assertIn("client_bundle_hash_for_ref", text)
        self.assertIn('NEW_CLIENT_REF="$compatible"', text)
        self.assertIn('data["client_repository_ref"] = client_ref', text)
        self.assertIn('data["client_compatible_refs"] = [', text)
        self.assertIn('echo "CLIENT_REF=$NEW_CLIENT_REF"', text)
        self.assertIn(
            'echo "CLIENT_COMPATIBLE_REFS=$COMPATIBLE_CLIENT_CSV"',
            text,
        )

    def test_update_server_creates_consistent_database_backup(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("$BACKUP/var/lib/hermes-rdp/state.sqlite3", text)
        self.assertIn("source.backup(destination)", text)
        self.assertIn('destination.execute("PRAGMA quick_check")', text)
        self.assertIn("update-metadata.json", text)
        self.assertIn('"resolved_sha": resolved_sha', text)

    def test_update_server_recovers_configured_default_rdp_service(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_RDP_CONFIGURED", text)
        self.assertIn(
            "SELECT value FROM settings WHERE key='default_rdp_device_id'",
            text,
        )
        self.assertIn(
            "systemctl enable --now bakunity-rdp-default.service",
            text,
        )
        self.assertIn(
            "systemctl disable --now bakunity-rdp-default.service",
            text,
        )

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

    def test_update_server_persists_immutable_source_snapshot(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("rm -rf /opt/hermes-rdp/source", text)
        self.assertIn("cp -a \"$ROOT\"/. /opt/hermes-rdp/source/", text)
        self.assertIn(
            "test -f /opt/hermes-rdp/source/scripts/setup-native-transport.sh",
            text,
        )
        self.assertIn(
            "test -f /opt/hermes-rdp/source/native-transport/go.mod",
            text,
        )
        self.assertLess(
            text.index("ROLLBACK_ARMED=1"),
            text.index("rm -rf /opt/hermes-rdp/source"),
        )

    def test_update_server_installs_cli_aliases_transactionally(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        for wrapper in (
            "/usr/local/bin/hermes-rdpctl",
            "/usr/local/bin/bakunity-rdpctl",
        ):
            self.assertIn(wrapper, text)
            self.assertIn(f"restore_optional_file {wrapper}", text)
            self.assertIn(f"{wrapper} doctor >/dev/null", text)
        self.assertIn(
            "export PYTHONPATH=/opt/hermes-rdp/app",
            text,
        )
        self.assertIn(
            'exec /usr/local/bin/hermes-rdpctl "$@"',
            text,
        )

    def test_update_server_migrates_and_preserves_web_admin_token(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("/etc/hermes-rdp/web-admin-token", text)
        self.assertIn("openssl rand -hex 32 > /etc/hermes-rdp/web-admin-token", text)
        self.assertIn("chown root:hermes-rdp /etc/hermes-rdp/web-admin-token", text)
        self.assertIn(
            "restore_optional_file /etc/hermes-rdp/web-admin-token",
            text,
        )

    def test_update_keeps_sqlite_runtime_files_owned_by_service_user(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'for sqlite_path in "$DB" "$DB-wal" "$DB-shm"; do',
            text,
        )
        self.assertIn('chown "$DB_UID:$DB_GID" "$sqlite_path"', text)
        self.assertIn('chmod "$DB_MODE" "$sqlite_path"', text)
        self.assertIn(
            "/usr/sbin/runuser -u hermes-rdp -- env "
            "PYTHONPATH=/opt/hermes-rdp/app",
            text,
        )
        self.assertIn(
            'if [[ "$(id -u)" -eq 0 && ! ( "${1:-}" == "admin" '
            '&& "${2:-}" == "password" ) ]]; then',
            text,
        )

    def test_plain_updater_refuses_major_frp_migration(self) -> None:
        text = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        self.assertIn("This server still uses FRP.", text)
        self.assertIn("install-server.sh with --migrate", text)


if __name__ == "__main__":
    unittest.main()
