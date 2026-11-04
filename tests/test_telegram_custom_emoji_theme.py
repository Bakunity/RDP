from __future__ import annotations

import unittest

from hermes_rdp.telegram_icons import (
    APPROVED_PACKS,
    ICONS,
    TelegramEmojiTheme,
)


class TelegramCustomEmojiThemeTests(unittest.TestCase):
    def test_only_user_approved_packs_are_registered(self) -> None:
        self.assertEqual(
            APPROVED_PACKS,
            (
                "tgiosicons",
                "vector_icons_by_fStikBot",
                "tgmacicons",
            ),
        )

    def test_theme_starts_with_visible_fallbacks_not_guessed_ids(self) -> None:
        required = {
            "computer",
            "back",
            "refresh",
            "repair",
            "delete",
            "success",
            "warning",
            "watch",
            "access_on",
            "access_off",
            "home",
            "globe",
            "add",
        }
        self.assertTrue(required.issubset(ICONS))
        for spec in ICONS.values():
            self.assertTrue(spec.fallback)
            self.assertTrue(spec.aliases)
            self.assertIsNone(spec.custom_emoji_id)
            self.assertIsNone(spec.pack)

    def test_unresolved_html_keeps_unicode_visible(self) -> None:
        theme = TelegramEmojiTheme()
        self.assertEqual(theme.html("computer"), ICONS["computer"].fallback)

    def test_unresolved_button_keeps_unicode_visible_and_style(self) -> None:
        theme = TelegramEmojiTheme()
        button = theme.button(
            "access_on",
            "ВКЛЮЧИТЬ ДОСТУП",
            callback_data="cmd:on:dev",
            style="success",
        )
        self.assertTrue(button["text"].startswith(ICONS["access_on"].fallback))
        self.assertNotIn("icon_custom_emoji_id", button)
        self.assertEqual(button["style"], "success")

    def test_runtime_pack_scan_resolves_real_custom_id_by_alias(self) -> None:
        theme = TelegramEmojiTheme()
        resolved = theme.learn_pack(
            "tgmacicons",
            {
                "stickers": [
                    {
                        "emoji": "💻",
                        "custom_emoji_id": "999999999999999999",
                    }
                ]
            },
        )
        self.assertGreaterEqual(resolved, 1)
        self.assertEqual(
            theme.icons["computer"].custom_emoji_id,
            "999999999999999999",
        )
        self.assertEqual(theme.icons["computer"].pack, "tgmacicons")
        self.assertEqual(theme.resolved_count(), 1)

    def test_resolved_html_uses_native_tg_emoji_entity(self) -> None:
        theme = TelegramEmojiTheme()
        theme.learn_pack(
            "tgiosicons",
            {
                "stickers": [
                    {
                        "emoji": "🔧",
                        "custom_emoji_id": "111111111111111111",
                    }
                ]
            },
        )
        rendered = theme.html("repair")
        self.assertIn('<tg-emoji emoji-id="111111111111111111">', rendered)
        self.assertIn(ICONS["repair"].fallback, rendered)

    def test_resolved_inline_button_uses_native_custom_icon(self) -> None:
        theme = TelegramEmojiTheme()
        theme.learn_pack(
            "tgiosicons",
            {
                "stickers": [
                    {
                        "emoji": "🔓",
                        "custom_emoji_id": "222222222222222222",
                    }
                ]
            },
        )
        button = theme.button(
            "access_on",
            "ВКЛЮЧИТЬ ДОСТУП",
            callback_data="cmd:on:dev",
            style="success",
        )
        self.assertEqual(button["text"], "ВКЛЮЧИТЬ ДОСТУП")
        self.assertEqual(
            button["icon_custom_emoji_id"],
            "222222222222222222",
        )
        self.assertEqual(button["style"], "success")

    def test_disabled_theme_falls_back_even_after_resolution(self) -> None:
        theme = TelegramEmojiTheme()
        theme.learn_pack(
            "tgiosicons",
            {
                "stickers": [
                    {
                        "emoji": "🛠️",
                        "custom_emoji_id": "333333333333333333",
                    }
                ]
            },
        )
        theme.enabled = False
        self.assertEqual(theme.html("repair"), ICONS["repair"].fallback)
        button = theme.button(
            "repair",
            "ВОССТАНОВИТЬ",
            callback_data="repair:dev",
            style="primary",
        )
        self.assertNotIn("icon_custom_emoji_id", button)
        self.assertTrue(button["text"].startswith(ICONS["repair"].fallback))
        self.assertEqual(button["style"], "primary")

    def test_higher_priority_pack_wins(self) -> None:
        theme = TelegramEmojiTheme()
        theme.learn_pack(
            "tgiosicons",
            {
                "stickers": [
                    {
                        "emoji": "💻",
                        "custom_emoji_id": "444444444444444444",
                    }
                ]
            },
        )
        theme.learn_pack(
            "tgmacicons",
            {
                "stickers": [
                    {
                        "emoji": "💻",
                        "custom_emoji_id": "555555555555555555",
                    }
                ]
            },
        )
        self.assertEqual(
            theme.icons["computer"].custom_emoji_id,
            "555555555555555555",
        )
        self.assertEqual(theme.icons["computer"].pack, "tgmacicons")


if __name__ == "__main__":
    unittest.main()
