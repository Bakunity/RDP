from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_rdp.bot import TelegramBot
from hermes_rdp.config import Config


class FakeRegistry:
    def __init__(self) -> None:
        self.settings = {
            "screen": "pair",
            "pair_code": "ABCD1234",
            "dashboard_message_id": "",
        }

    def get_setting(self, key: str, default: str = "") -> str:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


class TelegramPairCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        token = root / "telegram-token"
        fingerprint = root / "api.sha256"
        host_key = root / "ssh-host-key.pub"
        token.write_text("test-token", encoding="utf-8")
        fingerprint.write_text("AA11BB22", encoding="utf-8")
        host_key.write_text("ssh-ed25519 AAAATEST", encoding="utf-8")
        self.registry = FakeRegistry()
        self.config = Config(
            public_host="server.example",
            api_port=7443,
            ssh_bind_port=7000,
            ssh_user="hermes-tunnel",
            port_start=53389,
            port_end=53420,
            data_dir=root,
            db_path=root / "state.sqlite3",
            telegram_token_file=token,
            telegram_chat_id="123",
            tls_cert_file=root / "api.crt",
            tls_key_file=root / "api.key",
            tls_fingerprint_file=fingerprint,
            ssh_host_key_file=host_key,
            client_installer_url="https://example.test/install-client.ps1?a=1&b=2",
            repository_ref="server-ref",
            close_tunnel_helper=root / "close-tunnel",
            client_repository_ref="client-ref",
        )
        self.bot = TelegramBot(self.config, self.registry)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pair_command_is_one_compact_multiline_code_block(self) -> None:
        text, _ = self.bot._pair()
        self.assertEqual(text.count("<pre><code>"), 1)
        self.assertEqual(text.count("</code></pre>"), 1)
        self.assertIn("$s=(irm $u).TrimStart([char]0xFEFF)\n", text)
        self.assertIn("$p=@{\n", text)
        self.assertIn("Server=&#x27;server.example&#x27;", text)
        self.assertIn("PairCode=&#x27;ABCD1234&#x27;", text)
        self.assertIn("Fingerprint=&#x27;AA11BB22&#x27;", text)
        self.assertIn("RepositoryRef=&#x27;client-ref&#x27;", text)
        self.assertNotIn("RepositoryRef=&#x27;server-ref&#x27;", text)
        self.assertIn("a=1&amp;b=2", text)
        self.assertIn("&amp; ([scriptblock]::Create($s)) @p</code></pre>", text)
        self.assertNotIn("Create((irm $u))", text)
        self.assertNotIn("`", text)
        code = text.split("<pre><code>", 1)[1].split("</code></pre>", 1)[0]
        self.assertLess(max(map(len, code.splitlines())), 100)

    def test_render_requests_html_parse_mode(self) -> None:
        calls = []

        def fake_api_call(method, payload=None, timeout=40):
            calls.append((method, payload, timeout))
            return {"message_id": 77}

        self.bot.api_call = fake_api_call
        self.bot.render()
        method, payload, _ = calls[-1]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("<pre><code>", payload["text"])


if __name__ == "__main__":
    unittest.main()
