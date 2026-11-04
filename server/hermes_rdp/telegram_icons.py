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


# Curated IDs verified against the exact packs selected for Bakunity RDP.
# Keep these deterministic: buttons should use the intended artwork rather than
# whichever sticker happens to share the same fallback emoji first.
ICONS: dict[str, IconSpec] = {
    "computer": IconSpec("💻", ("💻", "🖥️", "🖥"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5258423306255604960", "tgmacicons"),
    "settings": IconSpec("⚙️", ("⚙️", "⚙"), APPROVED_PACKS, "5904258298764334001", "tgiosicons"),
    "back": IconSpec("⬅️", ("⬅️", "⬅"), APPROVED_PACKS, "5960671702059848143", "tgiosicons"),
    "refresh": IconSpec("🔄", ("🔄", "🔁"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5258420634785947640", "tgmacicons"),
    "repeat": IconSpec("🔁", ("🔁", "🔄"), APPROVED_PACKS, "6030657343744644592", "tgiosicons"),
    "repair": IconSpec("🔧", ("🔧", "🛠️", "🛠"), ("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons"), "5258023599419171861", "vector_icons_by_fStikBot"),
    "delete": IconSpec("🗑️", ("🗑️", "🗑"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5258130763148172425", "tgmacicons"),
    "cancel": IconSpec("❌", ("❌", "✖️", "✖"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5258226313285607065", "tgmacicons"),
    "success": IconSpec("✅", ("✅", "✔️", "✔"), ("vector_icons_by_fStikBot", "tgiosicons", "tgmacicons"), "5219899949281453881", "vector_icons_by_fStikBot"),
    "warning": IconSpec("❗️", ("❗️", "⚠️", "⚠"), APPROVED_PACKS, "6030563507299160824", "tgiosicons"),
    "info": IconSpec("ℹ️", ("ℹ️", "ℹ"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5258503720928288433", "tgmacicons"),
    "watch": IconSpec("👁", ("👁", "👁️"), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5253959125838090076", "tgmacicons"),
    "watch_off": IconSpec("👁", ("👁", "👁️"), APPROVED_PACKS, "6037243349675544634", "tgiosicons"),
    "download": IconSpec("⬇️", ("⬇️", "⬇"), APPROVED_PACKS, "6039802767931871481", "tgiosicons"),
    "upload": IconSpec("⬆️", ("⬆️", "⬆"), APPROVED_PACKS, "5963103826075456248", "tgiosicons"),
    "access_on": IconSpec("🔓", ("🔓",), APPROVED_PACKS, "6037496202990194718", "tgiosicons"),
    "access_off": IconSpec("🔒", ("🔒",), APPROVED_PACKS, "6037249452824072506", "tgiosicons"),
    "shield": IconSpec("🛡", ("🛡", "🛡️"), APPROVED_PACKS, "6030445631921721471", "tgiosicons"),
    "power": IconSpec("🛡", ("🛡", "🛡️"), APPROVED_PACKS, "6030537007350944596", "tgiosicons"),
    "home": IconSpec("🏠", ("🏠",), APPROVED_PACKS, "6042137469204303531", "tgiosicons"),
    "globe": IconSpec("🌐", ("🌐",), APPROVED_PACKS, "5776233299424843260", "tgiosicons"),
    "add": IconSpec("➕", ("➕",), ("tgmacicons", "tgiosicons", "vector_icons_by_fStikBot"), "5258108352008823107", "tgmacicons"),
    "play": IconSpec("▶️", ("▶️", "▶"), APPROVED_PACKS, "5773626993010546707", "tgiosicons"),
    "timer": IconSpec("⏲️", ("⏲️", "⏲"), APPROVED_PACKS, "6037268453759389862", "tgiosicons"),
    "list": IconSpec("🗂", ("🗂", "🗂️"), APPROVED_PACKS, "5766994197705921104", "tgiosicons"),
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
            if spec.custom_emoji_id and spec.pack:
                # Curated verified IDs are authoritative. Runtime discovery is
                # only a fallback for future icons that do not have a pinned ID.
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


    def pinned_ids(self) -> dict[str, tuple[str, str]]:
        return {
            name: (str(spec.custom_emoji_id), str(spec.pack))
            for name, spec in self.icons.items()
            if spec.custom_emoji_id and spec.pack
        }

    def invalidate_unverified(
        self,
        verified: dict[str, str],
    ) -> int:
        invalidated = 0
        for name, spec in tuple(self.icons.items()):
            if not spec.custom_emoji_id or not spec.pack:
                continue
            actual_pack = verified.get(str(spec.custom_emoji_id), "")
            if actual_pack.lower() == str(spec.pack).lower():
                continue
            self.icons[name] = replace(
                spec,
                custom_emoji_id=None,
                pack=None,
            )
            invalidated += 1
        return invalidated

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
        result: dict[str, Any] = {
            "text": text if custom_id else f"{spec.fallback} {text}",
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
