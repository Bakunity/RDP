from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IconSpec:
    fallback: str


# Bakunity RDP deliberately uses standard Unicode emoji here.
# They render consistently across Telegram clients and do not depend on
# Premium/custom-emoji support.
ICONS: dict[str, IconSpec] = {
    "computer": IconSpec("💻"),
    "settings": IconSpec("⚙️"),
    "edit": IconSpec("✏️"),
    "back": IconSpec("⬅️"),
    "refresh": IconSpec("🔄"),
    "repeat": IconSpec("🔁"),
    "repair": IconSpec("🔧"),
    "delete": IconSpec("🗑️"),
    "cancel": IconSpec("❌"),
    "success": IconSpec("✅"),
    "online": IconSpec("🟢"),
    "offline": IconSpec("🔴"),
    "warning": IconSpec("⚠️"),
    "info": IconSpec("ℹ️"),
    "watch": IconSpec("👁️"),
    "watch_off": IconSpec("⏸️"),
    "download": IconSpec("⬇️"),
    "upload": IconSpec("⬆️"),
    "access_on": IconSpec("🔓"),
    "access_off": IconSpec("🔒"),
    "shield": IconSpec("🛡️"),
    "power": IconSpec("⚡"),
    "home": IconSpec("🏠"),
    "globe": IconSpec("🌐"),
    "add": IconSpec("➕"),
    "play": IconSpec("▶️"),
    "timer": IconSpec("⏳"),
    "list": IconSpec("📋"),
}


class TelegramEmojiTheme:
    def __init__(self) -> None:
        self.icons = dict(ICONS)

    def html(self, name: str) -> str:
        return self.icons[name].fallback

    def button(
        self,
        name: str,
        text: str,
        *,
        callback_data: str,
        style: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "text": f"{self.icons[name].fallback} {text}",
            "callback_data": callback_data,
        }
        if style:
            result["style"] = style
        return result
