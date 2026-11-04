from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


APPROVED_PACKS = (
    "tgiosicons",
    "vector_icons_by_fStikBot",
    "tgmacicons",
)


def _normalize_emoji(value: str) -> str:
    return str(value or "").replace("\ufe0f", "").strip()


@dataclass(frozen=True)
class IconSpec:
    fallback: str
    aliases: tuple[str, ...]
    preferred_packs: tuple[str, ...] = APPROVED_PACKS
    custom_emoji_id: str | None = None
    pack: str | None = None


# No custom emoji IDs are hardcoded here. Telegram returns the actual IDs for
# the user's approved sets via getStickerSet at bot startup. Until an icon is
# resolved, the fallback remains visible so buttons can never become iconless.
ICONS: dict[str, IconSpec] = {
    "computer": IconSpec("🖥️", ("🖥️", "🖥", "💻", "⌨️"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot")),
    "settings": IconSpec("⚙️", ("⚙️", "⚙", "🛠️", "🔧")),
    "back": IconSpec("⬅️", ("⬅️", "⬅", "◀️", "↩️", "←")),
    "refresh": IconSpec("🔄", ("🔄", "🔁", "♻️")),
    "repeat": IconSpec("🔁", ("🔁", "🔄", "♻️")),
    "repair": IconSpec("🛠️", ("🛠️", "🛠", "🔧", "⚒️", "🪛"), ("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons")),
    "delete": IconSpec("🗑️", ("🗑️", "🗑", "❌")),
    "cancel": IconSpec("❌", ("❌", "✖️", "✖", "🚫")),
    "success": IconSpec("✅", ("✅", "✔️", "✔", "☑️", "🟢"), ("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons")),
    "warning": IconSpec("⚠️", ("⚠️", "⚠", "❗️", "❗"), ("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons")),
    "info": IconSpec("ℹ️", ("ℹ️", "ℹ", "❔", "❓")),
    "watch": IconSpec("👁️", ("👁️", "👁", "👀", "▶️")),
    "watch_off": IconSpec("⏸️", ("⏸️", "⏸", "⏹️", "👁️")),
    "download": IconSpec("⬇️", ("⬇️", "⬇", "📥", "↓")),
    "upload": IconSpec("⬆️", ("⬆️", "⬆", "📤", "↑")),
    "access_on": IconSpec("🔓", ("🔓", "🔑", "✅", "🟢")),
    "access_off": IconSpec("🔒", ("🔒", "⛔", "❌", "🔴")),
    "shield": IconSpec("🛡️", ("🛡️", "🛡", "✅")),
    "power": IconSpec("⚡", ("⚡", "🔌", "🔋")),
    "home": IconSpec("🏠", ("🏠", "🏡")),
    "globe": IconSpec("🌐", ("🌐", "🌍", "🌎", "🛜")),
    "add": IconSpec("➕", ("➕", "✚", "＋")),
    "play": IconSpec("▶️", ("▶️", "▶", "⏵")),
    "timer": IconSpec("⏳", ("⏳", "⏲️", "⌛")),
    "list": IconSpec("📋", ("📋", "🗂️", "🗂", "📊")),
}


class TelegramEmojiTheme:
    def __init__(self) -> None:
        self.enabled = True
        self.icons = dict(ICONS)

    def _pack_priority(self, spec: IconSpec, pack_name: str) -> int:
        try:
            return spec.preferred_packs.index(pack_name)
        except ValueError:
            return 999

    def learn_pack(self, pack_name: str, sticker_set: dict[str, Any] | None) -> int:
        if pack_name not in APPROVED_PACKS or not isinstance(sticker_set, dict):
            return 0

        by_alt: dict[str, str] = {}
        for sticker in sticker_set.get("stickers") or []:
            if not isinstance(sticker, dict):
                continue
            emoji = _normalize_emoji(str(sticker.get("emoji") or ""))
            custom_id = str(sticker.get("custom_emoji_id") or "")
            if emoji and custom_id and custom_id.isdigit() and emoji not in by_alt:
                by_alt[emoji] = custom_id

        resolved = 0
        for name, spec in tuple(self.icons.items()):
            if pack_name not in spec.preferred_packs:
                continue

            current_priority = (
                self._pack_priority(spec, spec.pack)
                if spec.pack
                else 999
            )
            candidate_priority = self._pack_priority(spec, pack_name)
            if candidate_priority > current_priority:
                continue

            custom_id = None
            for alias in spec.aliases:
                custom_id = by_alt.get(_normalize_emoji(alias))
                if custom_id:
                    break

            if custom_id:
                self.icons[name] = replace(
                    spec,
                    custom_emoji_id=custom_id,
                    pack=pack_name,
                )
                resolved += 1
        return resolved

    def resolved_count(self) -> int:
        return sum(1 for spec in self.icons.values() if spec.custom_emoji_id)

    def resolved_packs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(spec.pack)
                    for spec in self.icons.values()
                    if spec.custom_emoji_id and spec.pack
                }
            )
        )

    def html(self, name: str) -> str:
        spec = self.icons[name]
        if not self.enabled or not spec.custom_emoji_id:
            return spec.fallback
        return (
            f'<tg-emoji emoji-id="{spec.custom_emoji_id}">'
            f'{spec.fallback}</tg-emoji>'
        )

    def button(
        self,
        name: str,
        text: str,
        *,
        callback_data: str,
        style: str | None = None,
    ) -> dict[str, Any]:
        spec = self.icons[name]
        custom_id = spec.custom_emoji_id if self.enabled else None
        # Keep a visible Unicode icon in the label even when a native custom
        # emoji icon is attached. Some Telegram clients render button colors
        # from Bot API 9.4 but still omit icon_custom_emoji_id. This guarantees
        # that the action never becomes visually iconless.
        result: dict[str, Any] = {
            "text": f"{spec.fallback} {text}",
            "callback_data": callback_data,
        }
        if custom_id:
            result["icon_custom_emoji_id"] = custom_id
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
