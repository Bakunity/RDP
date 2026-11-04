from __future__ import annotations

import html
from typing import Any

from .bot import TelegramBot, escape


class TelegramUxBot(TelegramBot):
    """Telegram UX extensions that keep pairing and repair explicitly separate."""

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        data = str(callback.get("data", "home"))
        callback_id = str(callback.get("id", ""))

        if data == "pair_new":
            self._set_live(False)
            code = self.registry.create_pair_code(
                ttl_seconds=self.config.pair_ttl_seconds
            )
            self.registry.set_setting("pair_code", code)
            self.registry.set_setting("screen", "pair")
            self._answer(callback_id, "Новый код создан")
            self.render()
            return

        if data.startswith("repair:"):
            device_id = data.split(":", 1)[1]
            try:
                device = self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return

            telemetry = device.get("telemetry") or {}
            maintenance_capable = bool(telemetry.get("maintenance_capable"))
            if self._online(device) and maintenance_capable:
                self._set_live(False)
                self.registry.set_setting("selected_device", device_id)
                self.registry.set_setting("screen", "device")
                try:
                    self.registry.queue_command(device_id, "repair")
                    self._answer(
                        callback_id,
                        "Восстановление поставлено в очередь; выполнится, когда RDP будет свободен",
                    )
                except Exception as exc:
                    self._answer(callback_id, str(exc))
                self.render()
                return

            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "repair")
            self._answer(callback_id, "Для этого клиента нужен один ручной Repair")
            self.render()
            return

        super()._handle_callback(callback)

    def _pair(self) -> tuple[str, dict[str, Any]]:
        text, _ = super()._pair()
        guidance = (
            "Если установщик сообщил, что код истёк или уже использован, "
            "не запускай старую команду повторно — нажми «НОВЫЙ КОД» и "
            "скопируй обновлённую команду.\n\n"
        )
        text = text.replace("<pre><code>", guidance + "<pre><code>", 1)
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔁 НОВЫЙ КОД", "callback_data": "pair_new"}],
                [{"text": "⬅️ К СПИСКУ", "callback_data": "home"}],
            ]
        }
        return text, keyboard

    def _device(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        text, keyboard = super()._device(device)
        rows = list(keyboard.get("inline_keyboard", []))
        telemetry = device.get("telemetry") or {}
        automatic = self._online(device) and bool(telemetry.get("maintenance_capable"))
        rows.insert(
            max(0, len(rows) - 1),
            [
                {
                    "text": (
                        "🛠 ВОССТАНОВИТЬ АВТО"
                        if automatic
                        else "🛠 ВОССТАНОВИТЬ КЛИЕНТ"
                    ),
                    "callback_data": f"repair:{device['id']}",
                }
            ],
        )
        return text, {"inline_keyboard": rows}

    def _repair(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        repository_ref = self.config.repository_ref
        repair_url = (
            "https://raw.githubusercontent.com/bakunity/RDP/"
            f"{repository_ref}/scripts/repair-client.ps1"
        )
        command = (
            f"$u='{repair_url}'\n"
            "$s=(irm $u).TrimStart([char]0xFEFF)\n"
            "$p=@{\n"
            f"  RepositoryRef='{repository_ref}'\n"
            f"  ExpectedDeviceId='{device['id']}'\n"
            "}\n"
            "& ([scriptblock]::Create($s)) @p"
        )
        text = (
            "🛠 ВОССТАНОВЛЕНИЕ BAKUNITY RDP\n\n"
            f"Компьютер: {escape(device['display_name'])}\n"
            f"RDP: {self.config.public_host}:{device['rdp_port']}\n\n"
            "Этот fallback восстанавливает локальный Bakunity RDP Agent, Scheduled Task "
            "и необходимые RDP/OpenSSH-компоненты существующего подключения.\n\n"
            "Не создаёт новый компьютер и не меняет Device ID, API-token, "
            "Ed25519-ключи или назначенный RDP-порт.\n\n"
            "Для безопасного repair на ПК должны сохраниться device.json, "
            "существующая SSH-identity и known_hosts. Если они потеряны, repair "
            "остановится без автоматической перерегистрации.\n\n"
            "Этот экран нужен только для старого/offline клиента, который ещё не умеет self-heal.\n\n1. Открой PowerShell от имени администратора на этом ПК.\n"
            "2. Вставь команду ниже целиком.\n"
            "3. Дождись строки REPAIR=PASS.\n\n"
            f"<pre><code>{html.escape(command)}</code></pre>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "⬅️ К КОМПЬЮТЕРУ",
                        "callback_data": f"device:{device['id']}",
                    }
                ],
                [{"text": "🏠 К СПИСКУ", "callback_data": "home"}],
            ]
        }
        return text, keyboard

    def _render_content(self) -> tuple[str, dict[str, Any]]:
        screen = self.registry.get_setting("screen", "home") or "home"
        if screen == "repair":
            device_id = self.registry.get_setting("selected_device", "") or ""
            try:
                device = self.registry.get_device(device_id)
            except KeyError:
                self.registry.set_setting("screen", "home")
                self.registry.set_setting("selected_device", "")
                return self._home()
            return self._repair(device)
        return super()._render_content()
