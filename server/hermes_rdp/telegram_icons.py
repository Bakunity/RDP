from __future__ import annotations

from dataclasses import dataclass
from typing import Any


APPROVED_PACKS = (
    "tgiosicons",
    "vector_icons_by_fStikBot",
    "tgmacicons",
)


@dataclass(frozen=True)
class IconSpec:
    fallback: str
    custom_emoji_id: str
    pack: str = "tgiosicons"
    preferred_packs: tuple[str, ...] = APPROVED_PACKS


# Primary theme uses the adaptive Telegram iOS Icons pack for visual consistency.
# The bot may replace IDs at runtime with semantically matching icons from the
# user's other approved packs when Telegram exposes an exact fallback emoji.
ICONS: dict[str, IconSpec] = {
    "computer": IconSpec("🖥", "5942734685976138521", preferred_packs=("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot")),
    "settings": IconSpec("⚙️", "5904258298764334001"),
    "back": IconSpec("⬅️", "5960671702059848143"),
    "refresh": IconSpec("🔁", "6030657343744644592"),
    "repeat": IconSpec("🔁", "6030657343744644592"),
    "repair": IconSpec("🔧", "5962952497197748583", preferred_packs=("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons")),
    "delete": IconSpec("🗑", "6039522349517115015"),
    "cancel": IconSpec("❌", "5774077015388852135"),
    "success": IconSpec("✅", "5774022692642492953", preferred_packs=("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons")),
    "warning": IconSpec("❗️", "6030563507299160824", preferred_packs=("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons")),
    "info": IconSpec("ℹ", "6028435952299413210"),
    "watch": IconSpec("👁", "6037397706505195857"),
    "watch_off": IconSpec("👁", "6037243349675544634"),
    "download": IconSpec("⬇️", "6039802767931871481"),
    "upload": IconSpec("⬆️", "5963103826075456248"),
    "access_on": IconSpec("🔓", "6037496202990194718"),
    "access_off": IconSpec("🔒", "6037249452824072506"),
    "shield": IconSpec("🛡", "6030445631921721471"),
    "power": IconSpec("🛡", "6030537007350944596"),
    "home": IconSpec("🏠", "6042137469204303531"),
    "globe": IconSpec("🌐", "5776233299424843260"),
    "add": IconSpec("➕", "5882207227997066107"),
    "play": IconSpec("▶️", "5773626993010546707"),
    "timer": IconSpec("⏲️", "6037268453759389862"),
    "list": IconSpec("🗂", "5766994197705921104"),
}


class TelegramEmojiTheme:
    def __init__(self) -> None:
        self.enabled = True
        self.icons = dict(ICONS)

    def learn_pack(self, pack_name: str, sticker_set: dict[str, Any] | None) -> None:
        if pack_name not in APPROVED_PACKS or not isinstance(sticker_set, dict):
            return
        by_alt: dict[str, str] = {}
        for sticker in sticker_set.get("stickers") or []:
            if not isinstance(sticker, dict):
                continue
            emoji = str(sticker.get("emoji") or "")
            custom_id = str(sticker.get("custom_emoji_id") or "")
            if emoji and custom_id and emoji not in by_alt:
                by_alt[emoji] = custom_id
        if not by_alt:
            return
        for name, spec in tuple(self.icons.items()):
            if pack_name not in spec.preferred_packs:
                continue
            if spec.preferred_packs.index(pack_name) > 0:
                # A higher-priority pack remains preferred unless the currently
                # selected icon still comes from the static primary theme.
                current = self.icons[name]
                if current.pack in spec.preferred_packs[: spec.preferred_packs.index(pack_name)]:
                    continue
            custom_id = by_alt.get(spec.fallback)
            if custom_id:
                self.icons[name] = IconSpec(
                    fallback=spec.fallback,
                    custom_emoji_id=custom_id,
                    pack=pack_name,
                    preferred_packs=spec.preferred_packs,
                )

    def html(self, name: str) -> str:
        spec = self.icons[name]
        if not self.enabled:
            return spec.fallback
        return f'<tg-emoji emoji-id="{spec.custom_emoji_id}">{spec.fallback}</tg-emoji>'

    def button(
        self,
        name: str,
        text: str,
        *,
        callback_data: str,
        style: str | None = None,
    ) -> dict[str, Any]:
        spec = self.icons[name]
        result: dict[str, Any] = {
            "text": text if self.enabled else f"{spec.fallback} {text}",
            "callback_data": callback_data,
        }
        if self.enabled:
            result["icon_custom_emoji_id"] = spec.custom_emoji_id
            if style:
                result["style"] = style
        return result

    @staticmethod
    def payload_has_custom_emoji(payload: dict[str, Any]) -> bool:
        text = str(payload.get("text") or "")
        if "<tg-emoji " in text:
            return True
        keyboard = (payload.get("reply_markup") or {}).get("inline_keyboard") or []
        return any(
            isinstance(button, dict) and button.get("icon_custom_emoji_id")
            for row in keyboard
            for button in row
        )
