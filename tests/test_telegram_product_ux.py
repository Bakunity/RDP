from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TelegramProductUxTests(unittest.TestCase):
    def test_home_explains_computers_and_connection_devices(self) -> None:
        text = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        for marker in (
            "К ним подключаемся удалённо.",
            "Устройства подключения:",
            "С них подключаемся к компьютерам.",
            "⊞ ДОБАВИТЬ КОМПЬЮТЕР",
            "⊞ ДОБАВИТЬ УСТРОЙСТВО",
            "УСТРОЙСТВА ПОДКЛЮЧЕНИЯ",
        ):
            self.assertIn(marker, text)
        self.assertNotIn('"ОТКУДА ПОДКЛЮЧАЮСЬ"', text)

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

    def test_update_copy_is_explicitly_automatic(self) -> None:
        ux = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        technical = (ROOT / "server/hermes_rdp/bot.py").read_text(encoding="utf-8")
        self.assertIn("Bakunity RDP обновляется ", ux)
        self.assertIn("установится автоматически", ux)
        self.assertIn("система повторит попытку автоматически", ux)
        self.assertIn("ОБНОВЛЯЕТСЯ АВТОМАТИЧЕСКИ", technical)
        self.assertIn("ОБНОВИТСЯ АВТОМАТИЧЕСКИ", technical)
        self.assertIn("ОБНОВИТЬ СТАТУС", ux)


if __name__ == "__main__":
    unittest.main()
