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

    def test_core_icons_are_pinned_to_verified_pack_ids(self) -> None:
        expected = {
            "computer": ("5258423306255604960", "tgmacicons"),
            "refresh": ("5258420634785947640", "tgmacicons"),
            "repair": ("5258023599419171861", "vector_icons_by_fStikBot"),
            "delete": ("5258130763148172425", "tgmacicons"),
            "success": ("5219899949281453881", "vector_icons_by_fStikBot"),
            "back": ("5960671702059848143", "tgiosicons"),
            "access_on": ("6037496202990194718", "tgiosicons"),
            "access_off": ("6037249452824072506", "tgiosicons"),
            "watch": ("5253959125838090076", "tgmacicons"),
            "home": ("6042137469204303531", "tgiosicons"),
            "globe": ("5776233299424843260", "tgiosicons"),
            "add": ("5258108352008823107", "tgmacicons"),
        }
        for name, (custom_id, pack) in expected.items():
            self.assertEqual(ICONS[name].custom_emoji_id, custom_id)
            self.assertEqual(ICONS[name].pack, pack)

    def test_html_uses_pinned_native_custom_emoji(self) -> None:
        theme = TelegramEmojiTheme()
        rendered = theme.html("repair")
        self.assertIn(
            f'<tg-emoji emoji-id="{ICONS["repair"].custom_emoji_id}">',
            rendered,
        )
        self.assertIn(ICONS["repair"].fallback, rendered)

    def test_button_uses_only_native_pack_icon_when_enabled(self) -> None:
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
            ICONS["access_on"].custom_emoji_id,
        )
        self.assertEqual(button["style"], "success")

    def test_disabled_theme_falls_back_to_unicode(self) -> None:
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
        self.assertTrue(button["text"].startswith(ICONS["repair"].fallback))
        self.assertEqual(button["style"], "primary")

    def test_runtime_pack_scan_does_not_replace_curated_ids(self) -> None:
        theme = TelegramEmojiTheme()
        before = theme.icons["computer"]
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
        self.assertEqual(resolved, 0)
        self.assertEqual(theme.icons["computer"], before)

    def test_invalid_pinned_id_is_dropped_and_can_be_rediscovered(self) -> None:
        theme = TelegramEmojiTheme()
        invalidated = theme.reconcile_pack_membership(
            {
                str(ICONS["computer"].custom_emoji_id): "tgmacicons",
            },
            {
                "tgmacicons": "tgmacicons",
                "vector_icons_by_fStikBot": "vector_icons_by_fStikBot",
                "tgiosicons": "tgiosicons",
            },
        )
        self.assertGreater(invalidated, 0)
        self.assertIsNone(theme.icons["repair"].custom_emoji_id)
        self.assertIsNone(theme.icons["repair"].pack)

        resolved = theme.learn_pack(
            "vector_icons_by_fStikBot",
            {
                "stickers": [
                    {
                        "emoji": "🔧",
                        "custom_emoji_id": "777777777777777777",
                    }
                ]
            },
        )
        self.assertGreaterEqual(resolved, 1)
        self.assertEqual(
            theme.icons["repair"].custom_emoji_id,
            "777777777777777777",
        )
        self.assertEqual(
            theme.icons["repair"].pack,
            "vector_icons_by_fStikBot",
        )

    def test_button_fallback_does_not_disable_text_custom_emoji(self) -> None:
        theme = TelegramEmojiTheme()
        theme.buttons_enabled = False
        self.assertIn("<tg-emoji ", theme.html("computer"))

        button = theme.button(
            "add",
            "ДОБАВИТЬ ПК",
            callback_data="add",
            style="primary",
        )
        self.assertNotIn("icon_custom_emoji_id", button)
        self.assertTrue(button["text"].startswith(ICONS["add"].fallback))
        self.assertEqual(button["style"], "primary")

    def test_missing_pack_load_does_not_invalidate_curated_id(self) -> None:
        theme = TelegramEmojiTheme()
        before = theme.icons["computer"]
        invalidated = theme.reconcile_pack_membership(
            {},
            {
                "tgiosicons": "tgiosicons",
            },
        )
        self.assertGreater(invalidated, 0)
        self.assertEqual(theme.icons["computer"], before)
        self.assertEqual(
            theme.icons["computer"].custom_emoji_id,
            ICONS["computer"].custom_emoji_id,
        )
        self.assertEqual(theme.icons["computer"].pack, "tgmacicons")

    def test_all_pinned_ids_are_numeric_and_from_approved_packs(self) -> None:
        for spec in ICONS.values():
            self.assertTrue(spec.fallback)
            self.assertTrue(spec.aliases)
            self.assertIsNotNone(spec.custom_emoji_id)
            self.assertTrue(str(spec.custom_emoji_id).isdigit())
            self.assertIn(spec.pack, APPROVED_PACKS)


if __name__ == "__main__":
    unittest.main()
