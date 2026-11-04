from __future__ import annotations

import html
import time
from typing import Any

from .bot import TelegramBot, bar, escape, format_bytes, format_duration
from .db import normalize_device_slug
from .device_certificates import (
    get_device_certificate_target,
    set_device_slug_with_certificate,
)


class TelegramUxBot(TelegramBot):
    """Telegram UX extensions that keep pairing and repair explicitly separate."""

    def _delete_input_message(self, message: dict[str, Any]) -> None:
        message_id = message.get("message_id")
        chat_id = (message.get("chat") or {}).get("id")
        if not message_id or chat_id is None:
            return
        last_error: Exception | None = None
        for _ in range(2):
            try:
                self.api_call(
                    "deleteMessage",
                    {
                        "chat_id": chat_id,
                        "message_id": int(message_id),
                    },
                    timeout=15,
                )
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            import logging
            logging.getLogger("hermes_rdp.bot").warning(
                "accepted Telegram edit message delete failed: %s",
                last_error,
            )

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
                    self.registry.get_device(device_id)
                    if input_mode == "device_name":
                        self.registry.rename_device(device_id, raw_text)
                        self.registry.set_setting("input_mode", "")
                        self.registry.set_setting("input_error", "")
                        self.registry.set_setting("screen", "device")
                        # Accepted edit input is transient UI, not chat history.
                        self._delete_input_message(message)
                        self.render()
                        return

                    requested_slug = normalize_device_slug(raw_text)
                    if not requested_slug:
                        raise ValueError("Некорректный RDP-адрес")
                    domain = self._device_domain()
                    requested_host = (
                        f"{requested_slug}.{domain}"
                        if domain
                        else requested_slug
                    )
                    self.registry.set_setting(
                        "address_change_requested_host",
                        requested_host,
                    )
                    self.registry.set_setting(
                        "address_change_stage",
                        "issuing",
                    )
                    self.registry.set_setting("input_error", "")
                    self.registry.set_setting(
                        "screen",
                        "device_address_progress",
                    )
                    # Keep fast certificate telemetry flowing throughout the
                    # whole convergence window, not only the first 60 seconds.
                    self.registry.set_setting(
                        "live_until",
                        str(int(time.time()) + 180),
                    )
                    self.render()

                    try:
                        _, target = set_device_slug_with_certificate(
                            self.config,
                            self.registry,
                            device_id,
                            raw_text,
                        )
                    except Exception:
                        self.registry.set_setting(
                            "input_mode",
                            "device_slug",
                        )
                        self.registry.set_setting(
                            "screen",
                            "device_edit",
                        )
                        raise

                    self.registry.set_setting("input_mode", "")
                    self.registry.set_setting("input_error", "")
                    self.registry.set_setting(
                        "address_change_stage",
                        "applying",
                    )
                    if target:
                        self.registry.set_setting(
                            "address_change_target_thumbprint",
                            str(target.get("thumbprint") or ""),
                        )
                    # The user's input is accepted only after the server has a
                    # valid certificate for the new hostname.
                    self._delete_input_message(message)
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

        if data == "connectors":
            self._set_live(False)
            self.registry.set_setting("screen", "connectors")
            self.registry.set_setting("selected_connector", "")
            self._answer(callback_id)
            self.render()
            return

        if data == "connector_add":
            self._set_live(False)
            connector, token = self.registry.create_named_access_token(
                "Windows connector"
            )
            repository_ref = self._client_ref()
            installer_url = (
                "https://raw.githubusercontent.com/bakunity/RDP/"
                f"{repository_ref}/scripts/install-smart-route-connector.ps1"
            )

            def ps_quote(value: str) -> str:
                return str(value).replace("'", "''")

            command = (
                f"$u='{ps_quote(installer_url)}'; "
                "$s=(irm $u).TrimStart([char]0xFEFF); "
                "& ([scriptblock]::Create($s)) "
                f"-ApiBaseUrl '{ps_quote(self.config.api_base_url)}' "
                f"-ApiFingerprint '{ps_quote(self.config.tls_fingerprint)}' "
                f"-AccessToken '{ps_quote(token)}' "
                f"-RepositoryRef '{ps_quote(repository_ref)}'"
            )
            self.api_call(
                "sendMessage",
                {
                    "chat_id": self.config.telegram_chat_id,
                    "parse_mode": "HTML",
                    "text": (
                        f"{self.icon('add')} НОВЫЙ CONNECTOR\n\n"
                        "Открой PowerShell от администратора на Windows и "
                        "вставь команду целиком.\n\n"
                        f"<pre><code>{html.escape(command)}</code></pre>\n\n"
                        "Команда содержит секрет Connector. Не пересылай её."
                    ),
                },
            )
            self.registry.set_setting("screen", "connectors")
            self._answer(callback_id, "Команда Connector создана")
            self.render()
            return

        if data.startswith("connector:"):
            connector_id = data.split(":", 1)[1]
            try:
                self.registry.get_named_access_connector(connector_id)
            except KeyError:
                self._answer(callback_id, "Connector не найден")
                self.render()
                return
            self.registry.set_setting("selected_connector", connector_id)
            self.registry.set_setting("screen", "connector")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("route:"):
            _, policy, connector_id = data.split(":", 2)
            try:
                clean = self.registry.set_named_access_route_policy(
                    connector_id,
                    policy,
                )
            except Exception as exc:
                self._answer(callback_id, str(exc))
                return
            self.registry.set_setting("selected_connector", connector_id)
            self.registry.set_setting("screen", "connector")
            self._answer(callback_id, f"Маршрут: {clean.upper()}")
            self.render()
            return

        if data.startswith("connector_revoke:"):
            connector_id = data.split(":", 1)[1]
            try:
                self.registry.revoke_named_access_token(connector_id)
            except KeyError:
                self._answer(callback_id, "Connector не найден")
                return
            self.registry.set_setting("selected_connector", "")
            self.registry.set_setting("screen", "connectors")
            self._answer(callback_id, "Connector отозван")
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
        connectors = self.registry.list_named_access_tokens()
        connector_online = sum(
            1
            for connector in connectors
            if connector.get("last_seen")
            and int(time.time()) - int(connector["last_seen"]) <= 45
        )
        text = (
            f"{self.icon('computer')} BAKUNITY RDP\n\n"
            f"Хосты: {len(devices)} · в сети {online}\n"
            f"Коннекторы: {len(connectors)} · в сети {connector_online}\n\n"
            "Выбери Host или открой Connectors."
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
        rows.append([self.button("add", "ДОБАВИТЬ HOST", "add", style="primary")])
        rows.append([
            self.button(
                "globe",
                "КОННЕКТОРЫ",
                "connectors",
                style="primary",
            )
        ])
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

    def _product_rdp_endpoint(self, device: dict[str, Any]) -> str:
        default_device_id = str(
            self.registry.get_setting("default_rdp_device_id", "") or ""
        ).strip()
        if default_device_id == str(device.get("id") or ""):
            return self._device_host(device)
        return self._rdp_endpoint(device)

    def _connectors(self) -> tuple[str, dict[str, Any]]:
        connectors = self.registry.list_named_access_tokens()
        rows: list[list[dict[str, Any]]] = []
        now = int(time.time())
        for connector in connectors:
            last_seen = int(connector.get("last_seen") or 0)
            online = last_seen > 0 and now - last_seen <= 45
            machine = str(connector.get("machine_name") or "").strip()
            label = str(connector.get("name") or "Connector")
            if machine:
                label = f"{label} · {machine}"
            rows.append(
                [
                    self.button(
                        "online" if online else "offline",
                        label,
                        f"connector:{connector['id']}",
                        style="success" if online else None,
                    )
                ]
            )
        rows.append(
            [
                self.button(
                    "add",
                    "ДОБАВИТЬ CONNECTOR",
                    "connector_add",
                    style="primary",
                )
            ]
        )
        rows.append([self.button("back", "НАЗАД", "home")])
        text = (
            f"{self.icon('globe')} CONNECTORS\n\n"
            "Connector — Windows-компьютер, С КОТОРОГО ты подключаешься.\n\n"
            f"Всего: {len(connectors)}"
        )
        return text, {"inline_keyboard": rows}

    def _connector(
        self,
        connector: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        now = int(time.time())
        last_seen = int(connector.get("last_seen") or 0)
        online = last_seen > 0 and now - last_seen <= 45
        telemetry = connector.get("telemetry") or {}
        mesh = telemetry.get("mesh") or {}
        routes = telemetry.get("routes") or {}
        policy = str(connector.get("route_policy") or "auto").upper()
        route_names = {
            "lan": "LAN DIRECT",
            "p2p": "P2P DIRECT",
            "relay": "VPS RELAY",
            "unavailable": "НЕТ МАРШРУТА",
        }
        route_lines = []
        for device in self.registry.list_devices():
            route = routes.get(str(device["id"])) or {}
            raw_value = str(route.get("route") or "unavailable").lower()
            value = route_names.get(raw_value, raw_value.upper())
            latency = int(route.get("latency_ms") or 0)
            suffix = f" · {latency} мс" if latency > 0 else ""
            route_lines.append(
                f"{escape(device['display_name'])}: {escape(value)}{suffix}"
            )
        route_text = "\n".join(route_lines) or "Маршрутов ещё нет."
        if bool(mesh.get("conflict")):
            mesh_status = f"{self.icon('warning')} КОНФЛИКТ · ЧУЖОЙ TAILSCALE"
        elif bool(mesh.get("online")):
            mesh_status = f"{self.icon('success')} В СЕТИ"
        elif bool(mesh.get("installed")):
            mesh_status = f"{self.icon('timer')} ПОДКЛЮЧАЕТСЯ"
        else:
            mesh_status = f"{self.icon('info')} НЕ ПОДКЛЮЧЁН"
        text = (
            f"{self.icon('online' if online else 'offline')} "
            f"{escape(connector.get('name') or 'CONNECTOR').upper()} · "
            f"{'В СЕТИ' if online else 'НЕ В СЕТИ'}\n\n"
            f"Компьютер: {escape(connector.get('machine_name') or '—')}\n"
            f"Политика: {escape(policy)}\n"
            f"Mesh: {mesh_status}\n\n"
            "МАРШРУТЫ\n"
            f"{route_text}"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    self.button(
                        "success" if policy == "AUTO" else "info",
                        "AUTO",
                        f"route:auto:{connector['id']}",
                    ),
                    self.button(
                        "success" if policy == "P2P" else "info",
                        "P2P",
                        f"route:p2p:{connector['id']}",
                    ),
                ],
                [
                    self.button(
                        "success" if policy == "LAN" else "info",
                        "LAN",
                        f"route:lan:{connector['id']}",
                    ),
                    self.button(
                        "success" if policy == "RELAY" else "info",
                        "RELAY",
                        f"route:relay:{connector['id']}",
                    ),
                ],
                [
                    self.button(
                        "delete",
                        "ОТОЗВАТЬ CONNECTOR",
                        f"connector_revoke:{connector['id']}",
                        style="danger",
                    )
                ],
                [
                    self.button("refresh", "ОБНОВИТЬ", "refresh"),
                    self.button("back", "К CONNECTORS", "connectors"),
                ],
            ]
        }
        return text, keyboard

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
            f"Пользователь: {escape(telemetry.get('interactive_user') or '—')}\n"
            f"RDP: {self._product_rdp_endpoint(device)}"
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
                        "repair",
                        "ВОССТАНОВИТЬ",
                        f"repair:{device['id']}",
                        style="primary",
                    )
                ],
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
                f"Можно буквы, цифры и дефис.\n"
                f"Например: pc2 → pc2{suffix}"
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

    @staticmethod
    def _clean_thumbprint(value: Any) -> str:
        return "".join(
            character
            for character in str(value or "").upper()
            if character in "0123456789ABCDEF"
        )

    def _device_address_progress(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        stage = str(
            self.registry.get_setting(
                "address_change_stage",
                "issuing",
            )
            or "issuing"
        )
        requested_host = str(
            self.registry.get_setting(
                "address_change_requested_host",
                "",
            )
            or self._device_host(device)
        )
        telemetry = device.get("telemetry") or {}
        target = get_device_certificate_target(
            self.registry,
            str(device["id"]),
        )

        expected = self._clean_thumbprint(
            (target or {}).get("thumbprint")
            or self.registry.get_setting(
                "address_change_target_thumbprint",
                "",
            )
        )
        actual = self._clean_thumbprint(
            telemetry.get("rdp_certificate_thumbprint")
        )
        try:
            hash_type = int(
                telemetry.get("rdp_certificate_hash_type") or 0
            )
        except (TypeError, ValueError):
            hash_type = 0
        lifecycle_ok = bool(
            telemetry.get("certificate_lifecycle_ok")
        )
        applied = bool(
            stage != "issuing"
            and expected
            and actual == expected
            and hash_type == 3
            and lifecycle_ok
        )

        if applied:
            stage = "done"
            self.registry.set_setting(
                "address_change_stage",
                "done",
            )
            self._set_live(False)

        if stage == "issuing":
            lines = [
                f"{self.icon('globe')} ИЗМЕНЕНИЕ RDP-АДРЕСА",
                "",
                f"Новый адрес: {escape(requested_host)}",
                "",
                f"{self.icon('success')} 1/3 Запрос принят",
                f"{self.icon('timer')} 2/3 Выпускаю сертификат",
                "○ 3/3 Применение на компьютере",
                "",
                "Адрес ещё не считается готовым.",
            ]
            buttons = [
                [
                    self.button(
                        "refresh",
                        "ОБНОВИТЬ",
                        "refresh",
                    )
                ]
            ]
        elif stage == "done":
            lines = [
                f"{self.icon('success')} RDP-АДРЕС ГОТОВ",
                "",
                f"Адрес: {escape(requested_host)}",
                "",
                f"{self.icon('success')} 1/3 Адрес сохранён",
                f"{self.icon('success')} 2/3 Сертификат выпущен",
                f"{self.icon('success')} 3/3 Сертификат подтверждён компьютером",
                "",
                "Можно подключаться.",
            ]
            buttons = [
                [
                    self.button(
                        "back",
                        "К КОМПЬЮТЕРУ",
                        f"device:{device['id']}",
                        style="primary",
                    )
                ]
            ]
        else:
            try:
                rdp_connections = int(
                    telemetry.get("rdp_connections") or 0
                )
            except (TypeError, ValueError):
                rdp_connections = 0

            if not self._online(device):
                wait_text = (
                    "Компьютер сейчас не в сети. Применение продолжится "
                    "автоматически после подключения."
                )
            elif rdp_connections > 0:
                wait_text = (
                    "Есть активная RDP-сессия. Жду её завершения, "
                    "чтобы безопасно применить сертификат."
                )
            elif not actual:
                wait_text = (
                    "Жду подтверждение текущего сертификата от Windows."
                )
            else:
                wait_text = (
                    "Windows применяет новый сертификат. "
                    "Жду контрольное подтверждение."
                )

            lines = [
                f"{self.icon('globe')} ИЗМЕНЕНИЕ RDP-АДРЕСА",
                "",
                f"Новый адрес: {escape(requested_host)}",
                "",
                f"{self.icon('success')} 1/3 Адрес сохранён",
                f"{self.icon('success')} 2/3 Сертификат выпущен",
                f"{self.icon('timer')} 3/3 Применяю сертификат на компьютере",
                "",
                wait_text,
                "",
                "Готовность будет показана только после проверки Windows.",
            ]
            buttons = [
                [
                    self.button(
                        "refresh",
                        "ОБНОВИТЬ",
                        "refresh",
                    )
                ]
            ]

        return "\n".join(lines), {"inline_keyboard": buttons}

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
        if screen == "connectors":
            return self._connectors()
        if screen == "connector":
            connector_id = self.registry.get_setting(
                "selected_connector",
                "",
            ) or ""
            try:
                connector = self.registry.get_named_access_connector(
                    connector_id
                )
            except KeyError:
                self.registry.set_setting("screen", "connectors")
                return self._connectors()
            return self._connector(connector)
        if screen in {
            "repair",
            "device_details",
            "device_technical",
            "device_edit",
            "device_address_progress",
        }:
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
            if screen == "device_address_progress":
                return self._device_address_progress(device)
            return self._device_details(device)
        return super()._render_content()
