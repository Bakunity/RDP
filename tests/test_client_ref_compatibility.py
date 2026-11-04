from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hermes_rdp.bot import TelegramBot
from hermes_rdp.config import Config


class ClientRefCompatibilityTests(unittest.TestCase):
    def test_config_treats_equivalent_refs_as_same_client_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = Config(
                public_host="server.example",
                api_port=7443,
                ssh_bind_port=7000,
                ssh_user="hermes-tunnel",
                port_start=53389,
                port_end=53420,
                data_dir=root,
                db_path=root / "state.sqlite3",
                telegram_token_file=root / "telegram-token",
                telegram_chat_id="123",
                tls_cert_file=root / "api.crt",
                tls_key_file=root / "api.key",
                tls_fingerprint_file=root / "api.sha256",
                ssh_host_key_file=root / "ssh-host-key.pub",
                client_installer_url="https://example.test/install-client.ps1",
                repository_ref="server-ref",
                close_tunnel_helper=root / "close-tunnel",
                client_repository_ref=(
                    "ad29ce33ec8788a1fa93e45c65be2a609f9e203f"
                ),
                client_compatible_refs=(
                    "3aca607f86fac04aa678390de0afa9f20bd064a8",
                    "ad29ce33ec8788a1fa93e45c65be2a609f9e203f",
                ),
            )

            self.assertEqual(
                config.client_ref,
                "ad29ce33ec8788a1fa93e45c65be2a609f9e203f",
            )
            self.assertTrue(
                config.is_client_ref_compatible(
                    "3ACA607F86FAC04AA678390DE0AFA9F20BD064A8"
                )
            )
            self.assertFalse(
                config.is_client_ref_compatible(
                    "1111111111111111111111111111111111111111"
                )
            )
            self.assertEqual(
                config.compatible_client_refs,
                (
                    "ad29ce33ec8788a1fa93e45c65be2a609f9e203f",
                    "3aca607f86fac04aa678390de0afa9f20bd064a8",
                ),
            )

    def test_telegram_helper_supports_legacy_and_compatible_config_objects(self) -> None:
        bot = object.__new__(TelegramBot)

        bot.config = SimpleNamespace(
            repository_ref="server-ref",
            client_repository_ref=(
                "ad29ce33ec8788a1fa93e45c65be2a609f9e203f"
            ),
            client_compatible_refs=(
                "3aca607f86fac04aa678390de0afa9f20bd064a8",
            ),
        )
        self.assertTrue(
            bot._client_ref_is_compatible(
                "3aca607f86fac04aa678390de0afa9f20bd064a8"
            )
        )
        self.assertFalse(
            bot._client_ref_is_compatible(
                "2222222222222222222222222222222222222222"
            )
        )

        bot.config = SimpleNamespace(repository_ref="legacy-ref")
        self.assertEqual(bot._client_ref(), "legacy-ref")
        self.assertTrue(bot._client_ref_is_compatible("legacy-ref"))

    def test_api_returns_reported_ref_when_bundle_is_compatible(self) -> None:
        root = Path(__file__).resolve().parents[1]
        api = (root / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn(
            "self.server.config.is_client_ref_compatible(reported_client_ref)",
            api,
        )
        self.assertIn(
            "desired_client_ref = (",
            api,
        )
        self.assertIn(
            '"desired_client_ref": desired_client_ref',
            api,
        )


if __name__ == "__main__":
    unittest.main()
