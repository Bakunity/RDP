from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ZeroConfigServerInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bootstrap = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        self.advanced = (ROOT / "scripts/install-server.sh").read_text(encoding="utf-8")
        self.quickstart = (ROOT / "docs/QUICKSTART.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_bootstrap_is_interactive_but_token_safe(self) -> None:
        self.assertIn("read_masked_telegram_token", self.bootstrap)
        self.assertIn("read -r -s -n1 char </dev/tty", self.bootstrap)
        self.assertIn("printf '*' >/dev/tty", self.bootstrap)
        self.assertIn("for attempt in 1 2 3", self.bootstrap)
        self.assertIn("Telegram bot token пустой. Попробуйте ещё раз", self.bootstrap)
        self.assertIn("Telegram bot token не прошёл проверку getMe", self.bootstrap)
        self.assertIn("Telegram bot token не удалось подтвердить после 3 попыток", self.bootstrap)
        self.assertIn("telegram_call getMe", self.bootstrap)
        self.assertIn("telegram_call getWebhookInfo", self.bootstrap)
        self.assertNotIn("echo $TG_TOKEN", self.bootstrap)
        self.assertNotIn("printf '%s' \"$TG_TOKEN\"", self.bootstrap)

    def test_telegram_json_payload_shell_default_is_exact(self) -> None:
        self.assertNotIn('local payload="${2:-{}}"', self.bootstrap)
        self.assertIn('local payload="${2:-}"', self.bootstrap)
        self.assertIn("[[ -n \"$payload\" ]] || payload='{}'", self.bootstrap)
        command = (
            "set -- getMe '{}'; "
            "payload=\"${2:-}\"; "
            "[[ -n \"$payload\" ]] || payload='{}'; "
            "printf '%s' \"$payload\""
        )
        result = subprocess.run(
            ["bash", "-c", command],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "{}")

    def test_source_archive_server_scripts_are_executable(self) -> None:
        for relative in (
            "scripts/install-server.sh",
            "scripts/setup-trusted-rdp-cert.sh",
        ):
            mode = (ROOT / relative).stat().st_mode
            self.assertTrue(mode & 0o111, f"{relative} must be executable in Git archives")

    def test_owner_is_claimed_before_core_install(self) -> None:
        claim = self.bootstrap.index("/claim $CLAIM_CODE")
        owner = self.bootstrap.index("Telegram owner confirmed")
        install = self.bootstrap.index('"$SOURCE_ROOT/scripts/install-server.sh"')
        self.assertLess(claim, owner)
        self.assertLess(owner, install)
        self.assertIn('chat.get("type") != "private"', self.bootstrap)
        self.assertIn('str(chat.get("id", "")) != str(actor.get("id", ""))', self.bootstrap)
        self.assertIn('--telegram-chat-id "$OWNER_ID"', self.bootstrap)

    def test_public_ipv4_and_trusted_tls_are_automatic(self) -> None:
        self.assertIn("detect_public_ipv4", self.bootstrap)
        self.assertIn("api.ipify.org", self.bootstrap)
        self.assertIn("ipv4.icanhazip.com", self.bootstrap)
        self.assertIn('setup-trusted-rdp-cert.sh" --host "$PUBLIC_IPV4"', self.bootstrap)
        self.assertIn("Основной Hermes уже установлен и работает", self.bootstrap)
        # The advanced installer remains available and backward-compatible.
        self.assertIn("--trusted-rdp-cert", self.advanced)
        self.assertIn("--telegram-chat-id", self.advanced)

    def test_apt_preflight_handles_known_stale_debian_archive(self) -> None:
        self.assertIn("apt-get update -qq", self.bootstrap)
        self.assertIn("archive\\.debian\\.org/debian", self.bootstrap)
        self.assertIn("https://deb.debian.org/debian", self.bootstrap)
        self.assertIn("https://security.debian.org/debian-security", self.bootstrap)
        self.assertIn("apt-sources-", self.bootstrap)
        self.assertIn("Hermes ещё не устанавливался", self.bootstrap)

    def test_public_docs_offer_one_primary_server_command(self) -> None:
        command = (
            "curl -fsSL https://raw.githubusercontent.com/bakunity/RDP/main/"
            "scripts/install.sh | sudo bash"
        )
        self.assertIn(command, self.quickstart)
        self.assertIn(command, self.readme)
        self.assertNotIn("Базовая установка:", self.quickstart)
        self.assertNotIn("С trusted public-IP RDP certificate lifecycle:", self.quickstart)
        self.assertIn("/claim", self.quickstart)
        self.assertIn("advanced", self.quickstart.lower())


if __name__ == "__main__":
    unittest.main()
