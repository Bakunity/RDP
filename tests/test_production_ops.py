from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductionOpsTests(unittest.TestCase):
    def test_workflow_is_not_exposed_to_pull_request_code(self) -> None:
        text = (
            ROOT / ".github/workflows/production-ops.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("push:", text)
        self.assertIn("branches:", text)
        self.assertIn("- main", text)
        self.assertIn("issue_comment:", text)
        self.assertNotIn("pull_request:", text)
        self.assertIn("github.event.issue.number == 105", text)
        self.assertIn("\"OWNER\",\"MEMBER\",\"COLLABORATOR\"", text)
        self.assertIn("github.event.comment.body == '/doctor'", text)
        self.assertIn("github.event.comment.body == '/deploy'", text)
        self.assertIn("startsWith(github.event.comment.body, '/restart ')", text)
        self.assertIn("^[a-z0-9-]{1,48}$", text)
        self.assertIn("OPS_COMMENT:", text)
        self.assertIn("github.event.comment.body", text)
        self.assertNotIn('body="${{ github.event.comment.body }}"', text)

    def test_workflow_pins_server_host_key_and_uses_restricted_account(self) -> None:        text = (
            ROOT / ".github/workflows/production-ops.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("BAKUNITY_RDP_PROD_HOSTKEY_SHA256", text)
        self.assertIn("StrictHostKeyChecking=yes", text)
        self.assertIn("UserKnownHostsFile=", text)
        self.assertIn("ssh-keyscan", text)
        self.assertIn("ssh-keygen -lf", text)
        self.assertIn("bakunity-deploy@", text)
        self.assertNotIn("actions/checkout@", text)

    def test_server_access_is_forced_command_only(self) -> None:
        setup = (
            ROOT / "scripts/setup-github-ops-access.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("no-agent-forwarding", setup)
        self.assertIn("no-port-forwarding", setup)
        self.assertIn("no-X11-forwarding", setup)
        self.assertIn("no-pty", setup)
        self.assertIn('command="/usr/local/bin/bakunity-rdp-github-dispatch"', setup)
        self.assertIn("bakunity-rdp-github-dispatch.sh", setup)
        self.assertIn("NOPASSWD:", setup)
        self.assertIn("bakunity-rdp-github-ops", setup)
        self.assertNotIn("NOPASSWD: ALL", setup)

    def test_root_helper_only_deploys_current_main_or_runs_doctor(self) -> None:
        helper = (
            ROOT / "server/bin/bakunity-rdp-github-ops.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('case "${action}" in', helper)
        self.assertIn("doctor)", helper)
        self.assertIn("deploy)", helper)
        self.assertIn("restart)", helper)
        self.assertIn('"${CTL}" devices restart "${target}"', helper)
        self.assertIn("repos/${REPO}/commits/main", helper)
        self.assertIn('if [[ "${sha}" != "${main_sha}" ]]', helper)
        self.assertIn("DEPLOY=DENIED", helper)
        self.assertIn('env BAKUNITY_RDP_REF="${sha}" bash "${tmp}"', helper)
        self.assertIn('"${CTL}" doctor', helper)

    def test_server_updater_versions_privileged_ops_helper(self) -> None:
        update = (
            ROOT / "scripts/update-server.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'test -f "$ROOT/server/bin/bakunity-rdp-github-ops.sh"',
            update,
        )
        self.assertIn(
            '"$ROOT/server/bin/bakunity-rdp-github-ops.sh"',
            update,
        )
        self.assertIn(
            "/usr/local/sbin/bakunity-rdp-github-ops",
            update,
        )
        self.assertIn(
            "server/bin/bakunity-rdp-github-dispatch.sh",
            update,
        )
        self.assertIn(
            "/usr/local/bin/bakunity-rdp-github-dispatch",
            update,
        )
        self.assertIn(
            "restore_optional_file /usr/local/sbin/bakunity-rdp-github-ops",
            update,
        )


if __name__ == "__main__":
    unittest.main()
, text)
        self.assertIn('OPS_COMMENT: ${{ github.event.comment.body }}', text)
        self.assertNotIn('body="${{ github.event.comment.body }}"', text)

    def test_workflow_pins_server_host_key_and_uses_restricted_account(self) -> None:
        text = (
            ROOT / ".github/workflows/production-ops.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("BAKUNITY_RDP_PROD_HOSTKEY_SHA256", text)
        self.assertIn("StrictHostKeyChecking=yes", text)
        self.assertIn("UserKnownHostsFile=", text)
        self.assertIn("ssh-keyscan", text)
        self.assertIn("ssh-keygen -lf", text)
        self.assertIn("bakunity-deploy@", text)
        self.assertNotIn("actions/checkout@", text)

    def test_server_access_is_forced_command_only(self) -> None:
        setup = (
            ROOT / "scripts/setup-github-ops-access.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("no-agent-forwarding", setup)
        self.assertIn("no-port-forwarding", setup)
        self.assertIn("no-X11-forwarding", setup)
        self.assertIn("no-pty", setup)
        self.assertIn('command="/usr/local/bin/bakunity-rdp-github-dispatch"', setup)
        self.assertIn("SSH_ORIGINAL_COMMAND", setup)
        self.assertIn("NOPASSWD:", setup)
        self.assertIn("bakunity-rdp-github-ops", setup)
        self.assertNotIn("NOPASSWD: ALL", setup)

    def test_root_helper_only_deploys_current_main_or_runs_doctor(self) -> None:
        helper = (
            ROOT / "server/bin/bakunity-rdp-github-ops.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('case "${action}" in', helper)
        self.assertIn("doctor)", helper)
        self.assertIn("deploy)", helper)
        self.assertIn("repos/${REPO}/commits/main", helper)
        self.assertIn('if [[ "${sha}" != "${main_sha}" ]]', helper)
        self.assertIn("DEPLOY=DENIED", helper)
        self.assertIn('env BAKUNITY_RDP_REF="${sha}" bash "${tmp}"', helper)
        self.assertIn('"${CTL}" doctor', helper)

    def test_server_updater_versions_privileged_ops_helper(self) -> None:
        update = (
            ROOT / "scripts/update-server.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'test -f "$ROOT/server/bin/bakunity-rdp-github-ops.sh"',
            update,
        )
        self.assertIn(
            '"$ROOT/server/bin/bakunity-rdp-github-ops.sh"',
            update,
        )
        self.assertIn(
            "/usr/local/sbin/bakunity-rdp-github-ops",
            update,
        )
        self.assertIn(
            "restore_optional_file /usr/local/sbin/bakunity-rdp-github-ops",
            update,
        )


if __name__ == "__main__":
    unittest.main()
