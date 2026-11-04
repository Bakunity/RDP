from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_rdp.bot_ux import TelegramUxBot
from hermes_rdp.config import Config


class FakeRegistry:
    def __init__(self) -> None:
        self.settings = {
            "screen": "home",
            "pair_code": "",
            "selected_device": "",
            "dashboard_message_id": "",
            "live_until": "0",
        }
        self.devices = {
            "dev123": {
                "id": "dev123",
                "display_name": "TEST PC",
                "machine_name": "TESTPC",
                "rdp_port": 53391,
                "enabled": True,
                "last_seen": 0,
                "telemetry": {},
                "pending_command": "",
                "command_seq": 0,
                "last_result": {},
            }
        }
        self.pair_codes: list[str] = []
        self.queued_commands: list[tuple[str, str]] = []

    def get_setting(self, key: str, default: str = "") -> str:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    def create_pair_code(self, ttl_seconds: int = 900, **kwargs) -> str:
        code = f"PAIR{len(self.pair_codes) + 1:04d}"
        self.pair_codes.append(code)
        return code

    def get_device(self, device_id: str):
        if device_id not in self.devices:
            raise KeyError(device_id)
        return self.devices[device_id]

    def list_devices(self):
        return list(self.devices.values())

    def queue_command(self, device_id: str, action: str):
        self.queued_commands.append((device_id, action))
        return len(self.queued_commands)


class TelegramRepairUxTests(unittest.TestCase):
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
            client_installer_url="https://example.test/install-client.ps1",
            repository_ref="0123456789abcdef0123456789abcdef01234567",
            close_tunnel_helper=root / "close-tunnel",
        )
        self.bot = TelegramUxBot(self.config, self.registry)
        self.bot.render = lambda *args, **kwargs: None
        self.bot._answer = lambda *args, **kwargs: None

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_device_card_has_explicit_repair_button(self) -> None:
        _, keyboard = self.bot._device(self.registry.get_device("dev123"))
        buttons = [
            button
            for row in keyboard["inline_keyboard"]
            for button in row
        ]
        repair = [button for button in buttons if button["callback_data"] == "repair:dev123"]
        self.assertEqual(len(repair), 1)
        self.assertIn("ВОССТАНОВИТЬ", repair[0]["text"])

    def test_repair_screen_targets_existing_device(self) -> None:
        text, keyboard = self.bot._repair(self.registry.get_device("dev123"))
        self.assertIn("ВОССТАНОВЛЕНИЕ BAKUNITY RDP", text)
        self.assertIn("ExpectedDeviceId=&#x27;dev123&#x27;", text)
        self.assertIn("RepositoryRef=&#x27;0123456789abcdef0123456789abcdef01234567&#x27;", text)
        self.assertNotIn("PairCode", text)
        self.assertNotIn("install-client.ps1", text)
        callbacks = [button["callback_data"] for row in keyboard["inline_keyboard"] for button in row]
        self.assertIn("device:dev123", callbacks)
        self.assertIn("home", callbacks)

    def test_repair_callback_opens_repair_screen(self) -> None:
        self.bot._handle_callback({"id": "cb1", "data": "repair:dev123"})
        self.assertEqual(self.registry.get_setting("selected_device"), "dev123")
        self.assertEqual(self.registry.get_setting("screen"), "repair")

    def test_repair_callback_queues_one_click_maintenance_for_new_agent(self) -> None:
        self.registry.devices["dev123"]["telemetry"] = {"maintenance_capable": True}
        self.bot._online = lambda device: True
        self.bot._handle_callback({"id": "cb2", "data": "repair:dev123"})
        self.assertEqual(self.registry.queued_commands, [("dev123", "repair")])
        self.assertEqual(self.registry.get_setting("screen"), "device")

    def test_device_card_marks_automatic_repair_for_new_agent(self) -> None:
        self.registry.devices["dev123"]["telemetry"] = {"maintenance_capable": True}
        self.bot._online = lambda device: True
        _, keyboard = self.bot._device(self.registry.get_device("dev123"))
        labels = [
            button["text"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]
        self.assertTrue(
            any("ВОССТАНОВИТЬ АВТО" in label for label in labels)
        )
        repair = next(
            button
            for row in keyboard["inline_keyboard"]
            for button in row
            if button["callback_data"] == "repair:dev123"
        )
        self.assertTrue(repair["text"].startswith("🛠"))
        self.assertNotIn("icon_custom_emoji_id", repair)
        self.assertEqual(repair.get("style"), "primary")


    def test_semantic_button_colors_are_consistent(self) -> None:
        home_text, home_keyboard = self.bot._home()
        self.assertIn("BAKUNITY RDP", home_text)
        home_buttons = [
            button
            for row in home_keyboard["inline_keyboard"]
            for button in row
        ]
        add = next(button for button in home_buttons if button["callback_data"] == "add")
        refresh = next(
            button for button in home_buttons if button["callback_data"] == "refresh"
        )
        device = next(
            button
            for button in home_buttons
            if button["callback_data"] == "device:dev123"
        )
        self.assertEqual(add.get("style"), "primary")
        self.assertIsNone(refresh.get("style"))
        self.assertEqual(device.get("style"), "danger")

        self.bot._online = lambda device: True
        _, online_home = self.bot._home()
        online_device = next(
            button
            for row in online_home["inline_keyboard"]
            for button in row
            if button["callback_data"] == "device:dev123"
        )
        self.assertEqual(online_device.get("style"), "success")

        _, device_keyboard = self.bot._device(self.registry.get_device("dev123"))
        device_buttons = [
            button
            for row in device_keyboard["inline_keyboard"]
            for button in row
        ]
        by_callback = {button["callback_data"]: button for button in device_buttons}
        self.assertEqual(by_callback["cmd:off:dev123"].get("style"), "danger")
        self.assertEqual(by_callback["cmd:restart:dev123"].get("style"), "primary")
        self.assertEqual(by_callback["refresh"].get("style"), "primary")
        self.assertEqual(by_callback["live"].get("style"), "primary")
        self.assertEqual(by_callback["delete:dev123"].get("style"), "danger")
        self.assertIsNone(by_callback["home"].get("style"))

    def test_pairing_colors_keep_navigation_neutral(self) -> None:
        _, keyboard = self.bot._pair()
        buttons = {
            button["callback_data"]: button
            for row in keyboard["inline_keyboard"]
            for button in row
        }
        self.assertEqual(buttons["pair_new"].get("style"), "primary")
        self.assertIsNone(buttons["home"].get("style"))

    def test_pair_screen_can_rotate_code_without_reusing_old_one(self) -> None:
        self.bot._handle_callback({"id": "cb1", "data": "add"})
        first = self.registry.get_setting("pair_code")
        self.bot._handle_callback({"id": "cb2", "data": "pair_new"})
        second = self.registry.get_setting("pair_code")
        self.assertNotEqual(first, second)
        self.assertEqual(self.registry.get_setting("screen"), "pair")
        text, keyboard = self.bot._pair()
        self.assertIn(second, text)
        self.assertIn("код истёк или уже использован", text)
        callbacks = [button["callback_data"] for row in keyboard["inline_keyboard"] for button in row]
        self.assertIn("pair_new", callbacks)


if __name__ == "__main__":
    unittest.main()
