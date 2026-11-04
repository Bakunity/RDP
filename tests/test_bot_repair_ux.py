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
                "slug": "test-pc",
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


    def rename_device(self, device_id: str, name: str) -> None:
        clean = name.strip()
        if not clean:
            raise ValueError("name is empty")
        self.devices[device_id]["display_name"] = clean

    def set_device_slug(self, device_id: str, slug: str) -> str:
        clean = slug.strip().lower()
        if not clean:
            raise ValueError("invalid device slug")
        self.devices[device_id]["slug"] = clean
        return clean


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
            repository_ref="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            close_tunnel_helper=root / "close-tunnel",
            client_repository_ref="0123456789abcdef0123456789abcdef01234567",
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
        self.assertTrue(repair["text"].startswith("🔧"))
        self.assertIn("ВОССТАНОВИТЬ АВТО", repair["text"])
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
        self.assertTrue(device["text"].startswith("🔴"))

        self.bot._online = lambda device: True
        _, online_home = self.bot._home()
        online_device = next(
            button
            for row in online_home["inline_keyboard"]
            for button in row
            if button["callback_data"] == "device:dev123"
        )
        self.assertEqual(online_device.get("style"), "success")
        self.assertTrue(online_device["text"].startswith("🟢"))

        _, device_keyboard = self.bot._device(self.registry.get_device("dev123"))
        device_buttons = [
            button
            for row in device_keyboard["inline_keyboard"]
            for button in row
        ]
        by_callback = {button["callback_data"]: button for button in device_buttons}
        self.assertEqual(by_callback["cmd:off:dev123"].get("style"), "danger")
        self.assertEqual(by_callback["cmd:restart:dev123"].get("style"), "primary")
        self.assertIsNone(by_callback["refresh"].get("style"))
        self.assertIsNone(by_callback["details:dev123"].get("style"))
        self.assertIsNone(by_callback["home"].get("style"))
        self.assertNotIn("live", by_callback)
        self.assertNotIn("delete:dev123", by_callback)

        _, details_keyboard = self.bot._device_details(
            self.registry.get_device("dev123")
        )
        detail_buttons = [
            button
            for row in details_keyboard["inline_keyboard"]
            for button in row
        ]
        detail_callbacks = {
            button["callback_data"]: button for button in detail_buttons
        }
        self.assertEqual(detail_callbacks["refresh"].get("style"), "primary")
        self.assertEqual(detail_callbacks["delete:dev123"].get("style"), "danger")
        self.assertIn("live", detail_callbacks)
        self.assertIn("device:dev123", detail_callbacks)

    def test_device_summary_is_compact_and_details_keep_telemetry(self) -> None:
        device = self.registry.get_device("dev123")
        device["telemetry"] = {
            "os": "Windows 11 Pro",
            "interactive_user": "Tima",
            "cpu_percent": 12.5,
            "ram_percent": 44.0,
            "disk_percent": 55.0,
            "ssh_tunnel_running": True,
            "access_enabled": True,
            "sessions": ["Tima"],
        }
        self.bot._online = lambda value: True

        summary_text, summary_keyboard = self.bot._device(device)
        self.assertIn("TEST PC", summary_text)
        self.assertIn("Windows 11 Pro", summary_text)
        self.assertIn("RDP: server.example:53391", summary_text)
        self.assertIn("Доступ:", summary_text)
        self.assertIn("SSH-туннель:", summary_text)
        self.assertNotIn("CPU:", summary_text)
        self.assertNotIn("RAM:", summary_text)
        self.assertNotIn("Диск C:", summary_text)
        self.assertNotIn("Процессы", summary_text)
        summary_callbacks = {
            button["callback_data"]
            for row in summary_keyboard["inline_keyboard"]
            for button in row
        }
        self.assertIn("details:dev123", summary_callbacks)
        self.assertNotIn("delete:dev123", summary_callbacks)
        self.assertNotIn("live", summary_callbacks)

        details_text, details_keyboard = self.bot._device_details(device)
        self.assertIn("CPU:", details_text)
        self.assertIn("RAM:", details_text)
        self.assertIn("Диск C:", details_text)
        self.assertIn("Процессы", details_text)
        details_callbacks = {
            button["callback_data"]
            for row in details_keyboard["inline_keyboard"]
            for button in row
        }
        self.assertIn("delete:dev123", details_callbacks)
        self.assertIn("live", details_callbacks)
        self.assertIn("device:dev123", details_callbacks)

    def test_details_callback_opens_detailed_device_screen(self) -> None:
        self.bot._handle_callback({"id": "cb-details", "data": "details:dev123"})
        self.assertEqual(self.registry.get_setting("selected_device"), "dev123")
        self.assertEqual(self.registry.get_setting("screen"), "device_details")

    def test_start_recreates_dashboard_as_new_bot_message(self) -> None:
        calls = []
        self.bot.render = lambda *args, **kwargs: calls.append((args, kwargs))
        self.bot._handle_update(
            {
                "message": {
                    "text": "/start",
                    "chat": {"id": 123},
                    "from": {"id": 123},
                }
            }
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].get("force_new"))

    def test_device_card_exposes_name_and_address_edit_actions(self) -> None:
        _, keyboard = self.bot._device(self.registry.get_device("dev123"))
        callbacks = {
            button["callback_data"]
            for row in keyboard["inline_keyboard"]
            for button in row
        }
        self.assertIn("edit_name:dev123", callbacks)
        self.assertIn("edit_slug:dev123", callbacks)

    def test_edit_name_flow_updates_device_from_plain_message(self) -> None:
        self.bot._handle_callback({"id": "cb-name", "data": "edit_name:dev123"})
        self.assertEqual(self.registry.get_setting("screen"), "device_edit")
        self.assertEqual(self.registry.get_setting("input_mode"), "device_name")

        self.bot._handle_update(
            {
                "message": {
                    "text": "Рабочий ПК",
                    "chat": {"id": 123},
                    "from": {"id": 123},
                }
            }
        )
        self.assertEqual(
            self.registry.get_device("dev123")["display_name"],
            "Рабочий ПК",
        )
        self.assertEqual(self.registry.get_setting("screen"), "device")
        self.assertEqual(self.registry.get_setting("input_mode"), "")

    def test_edit_slug_flow_updates_named_endpoint(self) -> None:
        self.registry.set_setting("device_domain", "tima.biz")
        self.bot._handle_callback({"id": "cb-slug", "data": "edit_slug:dev123"})
        self.assertEqual(self.registry.get_setting("input_mode"), "device_slug")

        self.bot._handle_update(
            {
                "message": {
                    "text": "tima",
                    "chat": {"id": 123},
                    "from": {"id": 123},
                }
            }
        )
        device = self.registry.get_device("dev123")
        self.assertEqual(device["slug"], "tima")
        text, _ = self.bot._device(device)
        self.assertIn("RDP: tima.tima.biz:53391", text)

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
