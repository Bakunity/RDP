from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_rdp.db import Registry


ROOT = Path(__file__).resolve().parents[1]


class TelegramProductUxTests(unittest.TestCase):
    def test_home_is_computer_first_and_has_one_add_action(self) -> None:
        text = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        home = text.split("    def _home(", 1)[1].split(
            "    def _product_notice(",
            1,
        )[0]
        self.assertIn("МОИ КОМПЬЮТЕРЫ", home)
        self.assertIn('"add"', home)
        self.assertIn('"ДОБАВИТЬ КОМПЬЮТЕР"', home)
        self.assertNotIn("УСТРОЙСТВА ПОДКЛЮЧЕНИЯ", home)
        self.assertNotIn("connector_add", home)
        self.assertNotIn("⊞", home)

    def test_connection_devices_are_nested_inside_computer_settings(self) -> None:
        text = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        self.assertIn("def _device_settings", text)
        self.assertIn('"ПРЯМОЕ ПОДКЛЮЧЕНИЕ"', text)
        self.assertIn('f"connection:{device[\'id\']}"', text)
        self.assertIn("Это необязательно.", text)
        self.assertIn("через сервер Bakunity", text)
        self.assertIn("def _visible_connectors", text)
        self.assertIn('if int(connector.get("last_seen") or 0) > 0', text)
        self.assertIn("seen: set[str] = set()", text)

    def test_device_card_prioritizes_access_and_real_connection_state(self) -> None:
        text = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        product = text.split(
            "    def _device(self, device: dict[str, Any])",
            1,
        )[1].split("    def _device_edit(", 1)[0]
        self.assertIn("ПОДКЛЮЧЕНИЕ", product)
        self.assertIn("Доступ включён", product)
        self.assertIn("Подключение сейчас не активно", text)
        self.assertIn("ЧЕРЕЗ СЕРВЕР BAKUNITY", text)
        self.assertIn("ПРЯМОЕ ПОДКЛЮЧЕНИЕ", text)
        self.assertIn("ВЫКЛЮЧИТЬ ДОСТУП", product)
        self.assertIn("НАСТРОЙКИ", product)
        self.assertIn("ПОДРОБНЕЕ", product)
        self.assertNotIn("ПЕРЕЗАПУСТИТЬ ПОДКЛЮЧЕНИЕ", product)
        self.assertNotIn("ВОССТАНОВИТЬ", product)

    def test_details_unify_diagnostics_and_compact_update_status(self) -> None:
        text = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        self.assertIn("def _device_details", text)
        self.assertIn("ПОДКЛЮЧЕНИЕ", text)
        self.assertIn("СИСТЕМА", text)
        self.assertIn("BAKUNITY RDP", text)
        self.assertIn("Обновление Bakunity RDP · в процессе", text)
        self.assertIn("Актуальная версия", text)
        self.assertIn("Повторная попытка будет выполнена системой", text)
        self.assertIn("return self._device_details(device)", text)
        self.assertIn("Трафик сессии:", text)
        self.assertIn('route.get("active_sessions")', text)
        self.assertIn('route.get("bytes_received")', text)
        self.assertIn('route.get("bytes_sent")', text)

    def test_connector_install_command_stays_in_dashboard_screen(self) -> None:
        text = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        start = text.index('if data == "connector_add":')
        end = text.index('if data.startswith("connector:"):', start)
        block = text[start:end]
        self.assertIn('self.registry.set_setting("screen", "connector_add")', block)
        self.assertIn("_pending_connector_install_command", block)
        self.assertNotIn('"sendMessage"', block)
        self.assertIn('if data == "connector_add_done":', block)
        self.assertIn('if data == "connector_add_cancel":', block)
        self.assertIn("Одноразовый секрет не хранится", text)

    def test_connector_alias_can_be_renamed_without_touching_machine_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry = Registry(Path(temp) / "state.sqlite3", 53389, 53420)
            connector, _ = registry.create_named_access_token(
                "Windows устройство"
            )
            registry.rename_named_access_connector(
                connector["id"],
                "Рабочий ноутбук",
            )
            renamed = registry.get_named_access_connector(connector["id"])
            self.assertEqual(renamed["name"], "Рабочий ноутбук")
            self.assertIsNone(renamed["machine_name"])


if __name__ == "__main__":
    unittest.main()
