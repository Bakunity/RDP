from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StagingAutodeployTests(unittest.TestCase):
    def test_autodeploy_waits_for_green_ci_and_tracks_branch(self) -> None:
        script = (
            ROOT / "server/bin/hermes-rdp-autodeploy.sh"
        ).read_text(encoding="utf-8")
        for marker in (
            "git ls-remote",
            "actions/runs?head_sha=",
            'run.get("name") or "") == "CI"',
            'run.get("conclusion") == "success"',
            'write_status "waiting-ci"',
            'write_status "blocked"',
            'BAKUNITY_RDP_TRACK_REF="$TRACK_REF"',
            'BAKUNITY_RDP_AUTODEPLOY=1',
            '/usr/local/bin/bakunity-rdpctl doctor',
            'if [[ "$TRACK_REF" == "main" ]]',
        ):
            self.assertIn(marker, script)

    def test_autodeploy_timer_is_bounded_and_periodic(self) -> None:
        service = (
            ROOT / "server/systemd/hermes-rdp-autodeploy.service"
        ).read_text(encoding="utf-8")
        timer = (
            ROOT / "server/systemd/hermes-rdp-autodeploy.timer"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ConditionPathExists=/etc/hermes-rdp/autodeploy.enabled",
            service,
        )
        self.assertIn(
            "ExecStart=/usr/local/sbin/hermes-rdp-autodeploy",
            service,
        )
        self.assertIn("OnBootSec=45s", timer)
        self.assertIn("OnUnitActiveSec=60s", timer)
        self.assertIn("Persistent=true", timer)

    def test_web_admin_toggle_uses_bounded_sudo_only(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(
            encoding="utf-8"
        )
        helper = (
            ROOT / "server/bin/hermes-rdp-autodeploy-control.sh"
        ).read_text(encoding="utf-8")
        sudoers = (
            ROOT / "server/sudoers/hermes-rdp-autodeploy-control"
        ).read_text(encoding="utf-8")
        web = (ROOT / "server/hermes_rdp/admin_web.py").read_text(
            encoding="utf-8"
        )

        for marker in (
            'if path == "/v1/admin/autodeploy":',
            "def _admin_autodeploy",
            '"/usr/local/sbin/hermes-rdp-autodeploy-control"',
            "repository_requested_ref",
            "autodeploy requires a mutable non-main",
        ):
            self.assertIn(marker, api)

        self.assertIn('case "$1" in', helper)
        self.assertIn("on)", helper)
        self.assertIn("off)", helper)
        self.assertNotIn("eval ", helper)
        self.assertIn(
            "/usr/local/sbin/hermes-rdp-autodeploy-control on",
            sudoers,
        )
        self.assertIn(
            "/usr/local/sbin/hermes-rdp-autodeploy-control off",
            sudoers,
        )
        self.assertNotIn("NOPASSWD: ALL", sudoers)

        self.assertIn("function toggleAutodeploy()", web)
        self.assertIn("/v1/admin/autodeploy", web)
        self.assertIn("Auto deploy", web)
        self.assertIn("Tracking ref", web)

    def test_server_update_installs_and_rolls_back_autodeploy(self) -> None:
        update = (ROOT / "scripts/update-server.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            'TRACK_REF="${BAKUNITY_RDP_TRACK_REF:-$REF}"',
            'AUTODEPLOY_REQUESTED="${BAKUNITY_RDP_AUTODEPLOY:-0}"',
            "server/systemd/hermes-rdp-autodeploy.service",
            "server/systemd/hermes-rdp-autodeploy.timer",
            "server/bin/hermes-rdp-autodeploy.sh",
            "server/bin/hermes-rdp-autodeploy-control.sh",
            "server/sudoers/hermes-rdp-autodeploy-control",
            "/usr/local/sbin/hermes-rdp-autodeploy",
            "/usr/local/sbin/hermes-rdp-autodeploy-control",
            "/etc/systemd/system/hermes-rdp-autodeploy.timer",
            "/etc/hermes-rdp/autodeploy.enabled",
            "restore_optional_file /etc/systemd/system/hermes-rdp-autodeploy.timer",
            "restore_optional_file /usr/local/sbin/hermes-rdp-autodeploy",
            "restore_optional_file /etc/hermes-rdp/autodeploy.enabled",
            "systemctl enable --now hermes-rdp-autodeploy.timer",
            'python3 - "$TRACK_REF" "$RESOLVED_SHA"',
        ):
            self.assertIn(marker, update)

    def test_fresh_install_supports_opt_in_autodeploy(self) -> None:
        install = (ROOT / "scripts/install-server.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            "--autodeploy",
            'AUTODEPLOY="${BAKUNITY_RDP_AUTODEPLOY:-0}"',
            "git",
            '"repository_requested_ref": "$REF"',
            "hermes-rdp-autodeploy.service",
            "hermes-rdp-autodeploy.timer",
            "hermes-rdp-autodeploy-control.sh",
            "hermes-rdp-autodeploy-control",
        ):
            self.assertIn(marker, install)

    def test_config_keeps_requested_ref_backward_compatible(self) -> None:
        config = (ROOT / "server/hermes_rdp/config.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('repository_requested_ref: str = "main"', config)
        self.assertIn(
            'data.get("repository_requested_ref",',
            config,
        )


if __name__ == "__main__":
    unittest.main()
