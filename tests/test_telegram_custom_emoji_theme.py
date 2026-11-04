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

    def test_primary_theme_has_valid_custom_emoji_ids(self) -> None:
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
            self.assertTrue(spec.custom_emoji_id.isdigit())

    def test_html_uses_native_tg_emoji_entity(self) -> None:
        theme = TelegramEmojiTheme()
        rendered = theme.html("computer")
        self.assertIn("<tg-emoji emoji-id=", rendered)
        self.assertIn(ICONS["computer"].fallback, rendered)

    def test_inline_button_uses_native_custom_icon(self) -> None:
        theme = TelegramEmojiTheme()
        button = theme.button(
            "access_on",
            "ВКЛЮЧИТЬ ДОСТУП",
            callback_data="cmd:on:dev",
            style="success",
        )
        self.assertEqual(button["text"], "ВКЛЮЧИТЬ ДОСТУП")
        self.assertEqual(
            button["icon_custom_emoji_id"],
            theme.icons["access_on"].custom_emoji_id,
        )
        self.assertEqual(button["style"], "success")

    def test_unicode_fallback_keeps_bot_usable_without_premium(self) -> None:
        theme = TelegramEmojiTheme()
        theme.enabled = False
        self.assertEqual(theme.html("repair"), ICONS["repair"].fallback)
        button = theme.button(
            "repair",
            "ВОССТАНОВИТЬ",
            callback_data="repair:dev",
            style="primary",
        )
        self.assertNotIn("icon_custom_emoji_id", button)
        self.assertNotIn("style", button)
        self.assertTrue(button["text"].startswith(ICONS["repair"].fallback))

    def test_runtime_pack_scan_can_override_matching_semantic_icon(self) -> None:
        theme = TelegramEmojiTheme()
        theme.learn_pack(
            "tgmacicons",
            {
                "stickers": [
                    {
                        "emoji": "🖥",
                        "custom_emoji_id": "999999999999999999",
                    }
                ]
            },
        )
        self.assertEqual(
            theme.icons["computer"].custom_emoji_id,
            "999999999999999999",
        )
        self.assertEqual(theme.icons["computer"].pack, "tgmacicons")


if __name__ == "__main__":
    unittest.main()
