from __future__ import annotations

import unittest

from hermes_rdp.telegram_icons import ICONS, TelegramEmojiTheme


class TelegramEmojiThemeTests(unittest.TestCase):
    def test_standard_unicode_icons_are_used(self) -> None:
        expected = {
            "computer": "💻",
            "online": "🟢",
            "offline": "🔴",
            "refresh": "🔄",
            "repair": "🔧",
            "delete": "🗑️",
            "access_on": "🔓",
            "access_off": "🔒",
            "add": "➕",
        }
        for name, emoji in expected.items():
            self.assertEqual(ICONS[name].fallback, emoji)

    def test_html_returns_plain_unicode(self) -> None:
        theme = TelegramEmojiTheme()
        self.assertEqual(theme.html("computer"), "💻")
        self.assertNotIn("<tg-emoji", theme.html("computer"))

    def test_button_always_contains_visible_unicode_icon(self) -> None:
        theme = TelegramEmojiTheme()
        button = theme.button(
            "access_on",
            "ВКЛЮЧИТЬ ДОСТУП",
            callback_data="cmd:on:dev",
            style="success",
        )
        self.assertEqual(button["text"], "🔓 ВКЛЮЧИТЬ ДОСТУП")
        self.assertEqual(button["callback_data"], "cmd:on:dev")
        self.assertEqual(button["style"], "success")
        self.assertNotIn("icon_custom_emoji_id", button)

    def test_online_and_offline_status_use_round_dots(self) -> None:
        theme = TelegramEmojiTheme()
        online = theme.button(
            "online",
            "PC",
            callback_data="device:online",
            style="success",
        )
        offline = theme.button(
            "offline",
            "PC",
            callback_data="device:offline",
            style="danger",
        )
        self.assertEqual(online["text"], "🟢 PC")
        self.assertEqual(offline["text"], "🔴 PC")
        self.assertEqual(online["style"], "success")
        self.assertEqual(offline["style"], "danger")


if __name__ == "__main__":
    unittest.main()
