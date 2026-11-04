from __future__ import annotations

import html
from typing import Any

from .bot import TelegramBot, bar, escape, format_bytes, format_duration


class TelegramUxBot(TelegramBot):
    """Telegram UX extensions that keep pairing and repair explicitly separate."""

    def _handle_update(self, update: dict[str, Any]) -> None:
        if "message" in update and self._authorized(update):
            message = update.get("message") or {}
            raw_text = str(message.get("text") or "").strip()
            input_mode = str(self.registry.get_setting("input_mode", "") or "")
            device_id = str(
                self.registry.get_setting("selected_device", "") or ""
            )

            if input_mode in {"device_name", "device_slug"} and not raw_text.startswith("/"):
                try:
                    device = self.registry.get_device(device_id)
                    if input_mode == "device_name":
                        self.registry.rename_device(device_id, raw_text)
                    else:
                        self.registry.set_device_slug(device_id, raw_text)
                    self.registry.set_setting("input_mode", "")
                    self.registry.set_setting("input_error", "")
                    self.registry.set_setting("screen", "device")
                    message_id = message.get("message_id")
                    if message_id:
                        try:
                            self.api_call(
                                "deleteMessage",
                                {
                                    "chat_id": self.config.telegram_chat_id,
                                    "message_id": int(message_id),
                                },
                                timeout=15,
                            )
                        except Exception:
                            pass
                    self.render()
                except Exception as exc:
                    self.registry.set_setting("input_error", str(exc)[:180])
                    self.render()
                return

            if raw_text.split("@", 1)[0].lower() in {"/start", "/menu", "/status"}:
                self.registry.set_setting("input_mode", "")
                self.registry.set_setting("input_error", "")

        super()._handle_update(update)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        data = str(callback.get("data", "home"))
        callback_id = str(callback.get("id", ""))

        if not (
            data.startswith("edit_name:")
            or data.startswith("edit_slug:")
        ):
            self.registry.set_setting("input_mode", "")
            self.registry.set_setting("input_error", "")

        if data.startswith("edit_name:") or data.startswith("edit_slug:"):
            action, device_id = data.split(":", 1)
            try:
                self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting(
                "input_mode",
                "device_name" if action == "edit_name" else "device_slug",
            )
            self.registry.set_setting("input_error", "")
            self.registry.set_setting("screen", "device_edit")
            self._answer(
                callback_id,
                "Отправь новое имя"
                if action == "edit_name"
                else "Отправь новый адрес",
            )
            self.render()
            return

        if data.startswith("edit_cancel:"):
            device_id = data.split(":", 1)[1]
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("input_mode", "")
            self.registry.set_setting("input_error", "")
            self.registry.set_setting("screen", "device")
            self._answer(callback_id, "Изменение отменено")
            self.render()
            return

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

        if data.startswith("details:"):
            device_id = data.split(":", 1)[1]
            try:
                self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "device_details")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("technical:"):
            device_id = data.split(":", 1)[1]
            try:
                self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "device_technical")
            self._answer(callback_id)
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

    def _home(self) -> tuple[str, dict[str, Any]]:
        devices = self.registry.list_devices()
        online = sum(1 for device in devices if self._online(device))
        text = (
            f"{self.icon('computer')} BAKUNITY RDP\n\n"
            f"Компьютеры: {len(devices)}\n"
            f"В сети: {online}\n\n"
            "Выбери компьютер."
        )
        rows = []
        for device in devices:
            rows.append(
                [
                    self.button(
                        "online" if self._online(device) else "offline",
                        str(device["display_name"]),
                        f"device:{device['id']}",
                        style="success" if self._online(device) else "danger",
                    )
                ]
            )
        rows.append([self.button("add", "ДОБАВИТЬ ПК", "add", style="primary")])
        rows.append([self.button("refresh", "ОБНОВИТЬ", "refresh")])
        return text, {"inline_keyboard": rows}

    def _product_notice(self, device: dict[str, Any]) -> str:
        online = self._online(device)
        telemetry = device.get("telemetry") or {}
        if not online:
            return f"{self.icon('offline')} Нет связи с компьютером"

        desired_access = bool(device.get("enabled", True))
        if "access_enabled" in telemetry:
            applied_access = bool(telemetry.get("access_enabled"))
            if applied_access != desired_access:
                return f"{self.icon('warning')} Изменение доступа ещё применяется"

        if (
            bool(getattr(self.config, "trusted_rdp_certificate_enabled", False))
            and "certificate_lifecycle_ok" in telemetry
            and not bool(telemetry.get("certificate_lifecycle_ok"))
        ):
            return f"{self.icon('warning')} Защищённое подключение требует восстановления"

        if (
            "maintenance_capable" in telemetry
            and not bool(telemetry.get("maintenance_capable"))
        ):
            return f"{self.icon('warning')} Bakunity RDP требует восстановления"

        client_ref = str(telemetry.get("client_repository_ref") or "").lower()
        if client_ref and not self._client_ref_is_compatible(client_ref):
            return f"{self.icon('upload')} Доступно обновление Bakunity RDP"
        return ""

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
                [self.button("refresh", "НОВЫЙ КОД", "pair_new", style="primary")],
                [self.button("back", "К СПИСКУ", "home")],
            ]
        }
        return text, keyboard

    def _device(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        online = self._online(device)
        telemetry = device.get("telemetry") or {}
        desired_access = bool(device.get("enabled", True))
        pending_action = str(device.get("pending_command") or "")
        notice = self._product_notice(device)
        notice_text = f"\n\n{notice}" if notice else ""

        text = (
            f"{self.icon('online' if online else 'offline')} "
            f"{escape(device['display_name']).upper()} · "
            f"{'В СЕТИ' if online else 'НЕ В СЕТИ'}\n\n"
            f"{escape(device['machine_name'])} · "
            f"{escape(telemetry.get('os', '—'))}\n"
            f"RDP: {self._rdp_endpoint(device)}"
            f"{notice_text}"
        )

        if pending_action:
            control_rows = [
                [
                    self.button(
                        "timer",
                        "КОМАНДА ВЫПОЛНЯЕТСЯ",
                        "refresh",
                        style="primary",
                    )
                ]
            ]
        elif desired_access:
            control_rows = [
                [
                    self.button(
                        "access_off",
                        "ВЫКЛЮЧИТЬ ДОСТУП",
                        f"cmd:off:{device['id']}",
                        style="danger",
                    )
                ],
                [
                    self.button(
                        "repeat",
                        "ПЕРЕЗАПУСТИТЬ ПОДКЛЮЧЕНИЕ",
                        f"cmd:restart:{device['id']}",
                        style="primary",
                    )
                ],
            ]
        else:
            control_rows = [
                [
                    self.button(
                        "access_on",
                        "ВКЛЮЧИТЬ ДОСТУП",
                        f"cmd:on:{device['id']}",
                        style="success",
                    )
                ]
            ]

        keyboard = {
            "inline_keyboard": control_rows
            + [
                [
                    self.button(
                        "info",
                        "ПОДРОБНЕЕ",
                        f"details:{device['id']}",
                    )
                ],
                [
                    self.button(
                        "edit",
                        "ИЗМЕНИТЬ ИМЯ",
                        f"edit_name:{device['id']}",
                    )
                ],
                [
                    self.button(
                        "globe",
                        "ИЗМЕНИТЬ RDP-АДРЕС",
                        f"edit_slug:{device['id']}",
                    )
                ],
                [
                    self.button("refresh", "ОБНОВИТЬ", "refresh"),
                    self.button("back", "К СПИСКУ", "home"),
                ],
            ]
        }
        return text, keyboard

    def _device_edit(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        mode = str(self.registry.get_setting("input_mode", "") or "")
        error = str(self.registry.get_setting("input_error", "") or "")
        if mode == "device_name":
            title = "ИЗМЕНИТЬ ИМЯ"
            current = str(device.get("display_name") or "")
            hint = (
                "Отправь новое имя одним сообщением.\n"
                "Например: Офис"
            )
        else:
            title = "ИЗМЕНИТЬ RDP-АДРЕС"
            domain = self._device_domain()
            slug = str(device.get("slug") or "")
            current = f"{slug}.{domain}" if slug and domain else slug
            suffix = f".{domain}" if domain else ""
            hint = (
                f"Отправь только часть адреса до {suffix}.\n"
                f"Например: office → office{suffix}"
                if suffix
                else "Отправь новый адрес одним сообщением."
            )

        error_text = (
            f"\n\n{self.icon('warning')} Ошибка: {escape(error)}"
            if error
            else ""
        )
        text = (
            f"{self.icon('edit')} {title}\n\n"
            f"Сейчас: {escape(current)}\n\n"
            f"{hint}\n\n"
            "После сохранения твоё сообщение будет удалено из чата."
            f"{error_text}"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    self.button(
                        "cancel",
                        "ОТМЕНА",
                        f"edit_cancel:{device['id']}",
                    )
                ]
            ]
        }
        return text, keyboard

    def _device_details(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        telemetry = device.get("telemetry") or {}
        notice = self._product_notice(device)
        notice_text = f"{notice}\n\n" if notice else ""
        cpu = float(telemetry.get("cpu_percent", 0) or 0)
        ram = float(telemetry.get("ram_percent", 0) or 0)
        disk = float(telemetry.get("disk_percent", 0) or 0)

        if self._online(device) and "rdp_hermes_connections" in telemetry:
            through_bakunity = str(int(telemetry.get("rdp_hermes_connections", 0) or 0))
        else:
            through_bakunity = "—"
        if self._online(device) and "rdp_direct_connections" in telemetry:
            direct = str(int(telemetry.get("rdp_direct_connections", 0) or 0))
        else:
            direct = "—"

        sessions = telemetry.get("sessions") or []
        session_text = escape(", ".join(sessions) or "нет")
        text = (
            f"{self.icon('info')} "
            f"{escape(device['display_name']).upper()} · ПОДРОБНЕЕ\n\n"
            f"{notice_text}"
            "АКТИВНОСТЬ\n"
            f"Подключений через Bakunity: {through_bakunity}\n"
            f"Прямых подключений: {direct}\n"
            f"Сессии Windows: {session_text}\n"
            f"Аптайм: {format_duration(telemetry.get('uptime_seconds'))}\n\n"
            "РЕСУРСЫ\n"
            f"CPU: {cpu:.1f}%\n{bar(cpu)}\n\n"
            f"RAM: {ram:.1f}%\n{bar(ram)}\n"
            f"{format_bytes(telemetry.get('ram_used_bytes'))} / "
            f"{format_bytes(telemetry.get('ram_total_bytes'))}\n\n"
            f"Диск C: {disk:.1f}%\n{bar(disk)}\n"
            f"{format_bytes(telemetry.get('disk_used_bytes'))} / "
            f"{format_bytes(telemetry.get('disk_total_bytes'))}"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    self.button(
                        "info",
                        "ТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ",
                        f"technical:{device['id']}",
                    )
                ],
                [
                    self.button("refresh", "ОБНОВИТЬ", "refresh"),
                    self.button(
                        "back",
                        "К КОМПЬЮТЕРУ",
                        f"device:{device['id']}",
                    ),
                ],
            ]
        }
        return text, keyboard

    def _device_technical(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        text, keyboard = super()._device(device)
        text = (
            f"{self.icon('info')} ТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ\n\n"
            + text
        )[:4000]

        rows = list(keyboard.get("inline_keyboard", []))
        automatic = self._online(device) and bool(
            (device.get("telemetry") or {}).get("maintenance_capable")
        )
        repair_row = [
            self.button(
                "repair",
                "ВОССТАНОВИТЬ АВТО" if automatic else "ВОССТАНОВИТЬ КЛИЕНТ",
                f"repair:{device['id']}",
                style="primary",
            )
        ]
        if rows:
            rows.insert(max(0, len(rows) - 1), repair_row)
            last = list(rows[-1])
            replaced = []
            for button in last:
                if button.get("callback_data") == "home":
                    replaced.append(
                        self.button(
                            "back",
                            "К ПОДРОБНОСТЯМ",
                            f"details:{device['id']}",
                        )
                    )
                else:
                    replaced.append(button)
            rows[-1] = replaced
        else:
            rows = [
                repair_row,
                [
                    self.button(
                        "back",
                        "К ПОДРОБНОСТЯМ",
                        f"details:{device['id']}",
                    )
                ],
            ]
        return text, {"inline_keyboard": rows}

    def _repair(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        repository_ref = self._client_ref()
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
            f"{self.icon('repair')} ВОССТАНОВЛЕНИЕ BAKUNITY RDP\n\n"
            f"Компьютер: {escape(device['display_name'])}\n"
            f"RDP: {self._rdp_endpoint(device)}\n\n"
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
                    self.button(
                        "back",
                        "К КОМПЬЮТЕРУ",
                        f"device:{device['id']}",
                    )
                ],
                [self.button("home", "К СПИСКУ", "home")],
            ]
        }
        return text, keyboard

    def _render_content(self) -> tuple[str, dict[str, Any]]:
        screen = self.registry.get_setting("screen", "home") or "home"
        if screen in {"repair", "device_details", "device_technical", "device_edit"}:
            device_id = self.registry.get_setting("selected_device", "") or ""
            try:
                device = self.registry.get_device(device_id)
            except KeyError:
                self.registry.set_setting("screen", "home")
                self.registry.set_setting("selected_device", "")
                return self._home()
            if screen == "repair":
                return self._repair(device)
            if screen == "device_edit":
                return self._device_edit(device)
            if screen == "device_technical":
                return self._device_technical(device)
            return self._device_details(device)
        return super()._render_content()
