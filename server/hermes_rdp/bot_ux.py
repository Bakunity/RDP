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
from .native_transport import get_native_transport_host


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
            connector_id = str(
                self.registry.get_setting("selected_connector", "") or ""
            )

            if input_mode == "connector_name" and not raw_text.startswith("/"):
                try:
                    self.registry.rename_named_access_connector(
                        connector_id,
                        raw_text,
                    )
                    self.registry.set_setting("input_mode", "")
                    self.registry.set_setting("input_error", "")
                    self.registry.set_setting(
                        "screen",
                        "device_connection_source",
                    )
                    self._delete_input_message(message)
                    self.render()
                except Exception as exc:
                    self.registry.set_setting("input_error", str(exc)[:180])
                    self.render()
                return

            if (
                input_mode in {"device_name", "device_slug"}
                and not raw_text.startswith("/")
            ):
                try:
                    self.registry.get_device(device_id)
                    if input_mode == "device_name":
                        self.registry.rename_device(device_id, raw_text)
                        self.registry.set_setting("input_mode", "")
                        self.registry.set_setting("input_error", "")
                        self.registry.set_setting("screen", "device_settings")
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
                    self._delete_input_message(message)
                    self.render()
                except Exception as exc:
                    self.registry.set_setting("input_error", str(exc)[:180])
                    self.render()
                return

            if raw_text.split("@", 1)[0].lower() in {
                "/start",
                "/menu",
                "/status",
            }:
                self.registry.set_setting("input_mode", "")
                self.registry.set_setting("input_error", "")

        super()._handle_update(update)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        data = str(callback.get("data", "home"))
        callback_id = str(callback.get("id", ""))

        if not (
            data.startswith("edit_name:")
            or data.startswith("edit_slug:")
            or data.startswith("edit_connector:")
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
            self.registry.set_setting("screen", "device_settings")
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

        if data.startswith("settings:"):
            device_id = data.split(":", 1)[1]
            try:
                self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Компьютер не найден")
                self.render()
                return
            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "device_settings")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("edit_connector:"):
            connector_id = data.split(":", 1)[1]
            try:
                self.registry.get_named_access_connector(connector_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self.registry.set_setting("selected_connector", connector_id)
            self.registry.set_setting("input_mode", "connector_name")
            self.registry.set_setting("input_error", "")
            self.registry.set_setting("screen", "connector_edit")
            self._answer(callback_id, "Отправь новое имя")
            self.render()
            return

        if data.startswith("connector_edit_cancel:"):
            connector_id = data.split(":", 1)[1]
            self.registry.set_setting("selected_connector", connector_id)
            self.registry.set_setting("input_mode", "")
            self.registry.set_setting("input_error", "")
            self.registry.set_setting(
                "screen",
                "device_connection_source",
            )
            self._answer(callback_id, "Изменение отменено")
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
            self.registry.set_setting("screen", "device_details")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("connection:"):
            device_id = data.split(":", 1)[1]
            try:
                self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Компьютер не найден")
                self.render()
                return
            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("selected_connector", "")
            self.registry.set_setting("screen", "device_connection")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("connection_source:"):
            connector_id = data.split(":", 1)[1]
            device_id = self.registry.get_setting(
                "selected_device",
                "",
            ) or ""
            try:
                self.registry.get_device(device_id)
                self.registry.get_named_access_connector(connector_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self.registry.set_setting("selected_connector", connector_id)
            self.registry.set_setting("screen", "device_connection_source")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("connection_target:"):
            device_id = data.split(":", 1)[1]
            connector_id = self.registry.get_setting(
                "selected_connector",
                "",
            ) or ""
            try:
                self.registry.get_device(device_id)
                self.registry.get_named_access_connector(connector_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "device_connection_source")
            self._answer(callback_id)
            self.render()
            return

        if data.startswith("route_pair:"):
            policy = data.split(":", 1)[1]
            connector_id = self.registry.get_setting(
                "selected_connector",
                "",
            ) or ""
            device_id = self.registry.get_setting(
                "selected_device",
                "",
            ) or ""
            try:
                clean = self.registry.set_connector_device_route_policy(
                    connector_id,
                    device_id,
                    policy,
                )
            except Exception as exc:
                self._answer(callback_id, str(exc))
                return
            self.registry.set_setting("screen", "device_connection_source")
            self._answer(callback_id, f"Маршрут: {clean.upper()}")
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

            # A pending command contains a one-time connector token. Never
            # persist that plaintext token in SQLite. If the previous command
            # was abandoned before first contact, revoke it before creating a
            # replacement.
            pending_id = str(
                self.registry.get_setting(
                    "pending_connector_add_id",
                    "",
                )
                or ""
            )
            if pending_id:
                try:
                    pending = self.registry.get_named_access_connector(
                        pending_id
                    )
                    if not int(pending.get("last_seen") or 0):
                        self.registry.revoke_named_access_token(pending_id)
                except KeyError:
                    pass

            connector, token = self.registry.create_named_access_token(
                "Windows устройство"
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
            self._pending_connector_install_command = command
            self.registry.set_setting(
                "pending_connector_add_id",
                str(connector["id"]),
            )
            self.registry.set_setting("screen", "connector_add")
            self._answer(callback_id, "Команда подключения создана")
            self.render()
            return

        if data == "connector_add_done":
            self._pending_connector_install_command = ""
            self.registry.set_setting("pending_connector_add_id", "")
            target_screen = (
                "device_connection"
                if self.registry.get_setting("selected_device", "")
                else "home"
            )
            self.registry.set_setting("screen", target_screen)
            self._answer(callback_id)
            self.render()
            return

        if data == "connector_add_cancel":
            pending_id = str(
                self.registry.get_setting(
                    "pending_connector_add_id",
                    "",
                )
                or ""
            )
            if pending_id:
                try:
                    pending = self.registry.get_named_access_connector(
                        pending_id
                    )
                    if not int(pending.get("last_seen") or 0):
                        self.registry.revoke_named_access_token(pending_id)
                except KeyError:
                    pass
            self._pending_connector_install_command = ""
            self.registry.set_setting("pending_connector_add_id", "")
            target_screen = (
                "device_connection"
                if self.registry.get_setting("selected_device", "")
                else "home"
            )
            self.registry.set_setting("screen", target_screen)
            self._answer(callback_id, "Добавление отменено")
            self.render()
            return

        if data.startswith("connector:"):
            connector_id = data.split(":", 1)[1]
            try:
                self.registry.get_named_access_connector(connector_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
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
                self._answer(callback_id, "Устройство не найдено")
                return
            self.registry.set_setting("selected_connector", "")
            target_screen = (
                "device_connection"
                if self.registry.get_setting("selected_device", "")
                else "home"
            )
            self.registry.set_setting("screen", target_screen)
            self._answer(callback_id, "Устройство удалено")
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
        text = (
            f"{self.icon('computer')} BAKUNITY RDP\n\n"
            "МОИ КОМПЬЮТЕРЫ"
        )
        rows: list[list[dict[str, Any]]] = []
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
        if not devices:
            text += "\n\nКомпьютеров пока нет."
        rows.append(
            [
                self.button(
                    "add",
                    "ДОБАВИТЬ КОМПЬЮТЕР",
                    "add",
                    style="primary",
                )
            ]
        )
        rows.append(
            [
                self.button(
                    "refresh",
                    "ОБНОВИТЬ СТАТУС",
                    "refresh",
                )
            ]
        )
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
                return (
                    f"{self.icon('warning')} Изменение доступа ещё применяется"
                )

        if (
            bool(
                getattr(
                    self.config,
                    "trusted_rdp_certificate_enabled",
                    False,
                )
            )
            and "certificate_lifecycle_ok" in telemetry
            and not bool(telemetry.get("certificate_lifecycle_ok"))
        ):
            return (
                f"{self.icon('warning')} "
                "Защищённое подключение требует восстановления"
            )

        if (
            "maintenance_capable" in telemetry
            and not bool(telemetry.get("maintenance_capable"))
        ):
            return (
                f"{self.icon('warning')} "
                "Bakunity RDP требует восстановления"
            )

        client_ref = str(
            telemetry.get("client_repository_ref") or ""
        ).lower()
        desired_ref = self._client_ref().lower()
        maintenance = telemetry.get("maintenance_status") or {}
        state = str(maintenance.get("state") or "").lower()
        action = str(maintenance.get("action") or "").lower()
        target = str(maintenance.get("repository_ref") or "").lower()
        current_update = bool(
            action == "update"
            and desired_ref
            and target == desired_ref
        )

        if current_update and state == "running":
            return (
                f"{self.icon('refresh')} "
                "ОБНОВЛЕНИЕ BAKUNITY RDP · В ПРОЦЕССЕ"
            )
        if (
            client_ref
            and not self._client_ref_is_compatible(client_ref)
            and current_update
            and state == "failed"
        ):
            return (
                f"{self.icon('warning')} "
                "Обновление Bakunity RDP не завершено · "
                "система повторит попытку"
            )
        if client_ref and not self._client_ref_is_compatible(client_ref):
            return (
                f"{self.icon('refresh')} "
                "ОБНОВЛЕНИЕ BAKUNITY RDP · ОЖИДАЕТ ЗАПУСКА"
            )
        return ""

    def _product_rdp_endpoint(self, device: dict[str, Any]) -> str:
        # Product identity is stable and portless. Smart Route uses a
        # connector-local port while the public OpenSSH port is fallback-only.
        return self._device_host(device)

    def _visible_connectors(self) -> list[dict[str, Any]]:
        connectors = [
            connector
            for connector in self.registry.list_named_access_tokens()
            if int(connector.get("last_seen") or 0) > 0
        ]
        connectors.sort(
            key=lambda item: (
                int(item.get("last_seen") or 0),
                int(item.get("updated_at") or 0),
                int(item.get("created_at") or 0),
            ),
            reverse=True,
        )
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for connector in connectors:
            machine = str(connector.get("machine_name") or "").strip()
            key = machine.casefold() if machine else str(connector.get("id"))
            if key in seen:
                continue
            seen.add(key)
            result.append(connector)
        return result

    @staticmethod
    def _connector_display_name(connector: dict[str, Any]) -> str:
        machine = str(connector.get("machine_name") or "").strip()
        name = str(connector.get("name") or "").strip()
        generic = {
            "",
            "Windows connector",
            "Windows Connector",
            "Windows устройство",
            "Windows device",
        }
        if name not in generic:
            return name
        return machine or "Windows"

    @staticmethod
    def _policy_label(value: str) -> str:
        return {
            "auto": "АВТО",
            "p2p": "ТОЛЬКО P2P",
            "lan": "ТОЛЬКО LAN",
            "relay": "ТОЛЬКО RELAY",
        }.get(str(value or "").lower(), "АВТО")

    def _active_connection_state(
        self,
        device: dict[str, Any],
    ) -> dict[str, Any]:
        device_id = str(device.get("id") or "")
        telemetry = device.get("telemetry") or {}
        try:
            windows_sessions = int(
                telemetry.get("rdp_user_sessions") or 0
            )
        except (TypeError, ValueError):
            windows_sessions = 0

        # A transport stream or TCP socket is not proof that a user actually
        # established an RDP session. Windows host session state is the gate.
        if windows_sessions <= 0:
            return {
                "active": False,
                "route": "inactive",
                "label": "⚪ Подключение сейчас не активно",
                "latency_ms": 0,
                "bytes_received": 0,
                "bytes_sent": 0,
                "sessions": 0,
                "source": "",
                "exact": True,
            }

        for connector in self._visible_connectors():
            connector_telemetry = connector.get("telemetry") or {}
            route = (
                connector_telemetry.get("routes") or {}
            ).get(device_id) or {}
            try:
                transport_sessions = int(
                    route.get("active_sessions") or 0
                )
            except (TypeError, ValueError):
                transport_sessions = 0
            if transport_sessions <= 0:
                continue
            route_name = str(route.get("route") or "unavailable")
            try:
                latency = int(route.get("latency_ms") or 0)
            except (TypeError, ValueError):
                latency = 0
            try:
                received = int(route.get("bytes_received") or 0)
            except (TypeError, ValueError):
                received = 0
            try:
                sent = int(route.get("bytes_sent") or 0)
            except (TypeError, ValueError):
                sent = 0
            return {
                "active": True,
                "route": route_name,
                "label": self._route_label(route_name),
                "latency_ms": latency,
                "bytes_received": received,
                "bytes_sent": sent,
                "sessions": windows_sessions,
                "source": self._connector_display_name(connector),
                "exact": True,
            }

        native = get_native_transport_host(
            self.registry,
            device_id,
        )
        try:
            native_sessions = int(native.get("active_sessions") or 0)
        except (TypeError, ValueError):
            native_sessions = 0
        native_path = str(native.get("path") or "").lower()
        if native_sessions > 0 and native_path in {"direct", "relay"}:
            route = (
                "native_p2p"
                if native_path == "direct"
                else "native_relay"
            )
            return {
                "active": True,
                "route": route,
                "label": self._route_label(route),
                "latency_ms": 0,
                "bytes_received": 0,
                "bytes_sent": 0,
                "sessions": windows_sessions,
                "source": "",
                "exact": True,
            }

        # Windows confirms a real RDP user session, but the exact transport
        # route is not known. Never guess server/direct from TCP socket counts.
        return {
            "active": True,
            "route": "rdp",
            "label": "🟢 RDP ПОДКЛЮЧЕНО",
            "latency_ms": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "sessions": windows_sessions,
            "source": "",
            "exact": True,
        }

    def _update_status_text(self, device: dict[str, Any]) -> str:
        telemetry = device.get("telemetry") or {}
        client_ref = str(
            telemetry.get("client_repository_ref") or ""
        ).lower()
        desired_ref = self._client_ref().lower()
        maintenance = telemetry.get("maintenance_status") or {}
        state = str(maintenance.get("state") or "").lower()
        action = str(maintenance.get("action") or "").lower()
        target = str(maintenance.get("repository_ref") or "").lower()
        current_update = bool(
            action == "update"
            and desired_ref
            and target == desired_ref
        )
        version = client_ref[:7] if client_ref else "—"
        target_version = desired_ref[:7] if desired_ref else "—"

        if current_update and state == "running":
            return (
                f"{self.icon('refresh')} Обновление Bakunity RDP · в процессе\n"
                f"Версия: {version} → {target_version}"
            )
        if current_update and state == "failed":
            return (
                f"{self.icon('warning')} "
                "Обновление Bakunity RDP не завершено\n"
                "Повторная попытка будет выполнена системой"
            )
        if client_ref and self._client_ref_is_compatible(client_ref):
            return (
                f"{self.icon('success')} Актуальная версия · {version}"
            )
        if client_ref:
            return (
                f"{self.icon('refresh')} "
                "Обновление Bakunity RDP · ожидает запуска\n"
                f"Версия: {version} → {target_version}"
            )
        return f"{self.icon('info')} Версия Bakunity RDP: —"

    def _connectors(self) -> tuple[str, dict[str, Any]]:
        text = (
            f"{self.icon('info')} ПРЯМОЕ ПОДКЛЮЧЕНИЕ\n\n"
            "Теперь оно настраивается внутри конкретного компьютера. "
            "Открой компьютер → Настройки → Прямое подключение."
        )
        return text, {
            "inline_keyboard": [
                [self.button("back", "К КОМПЬЮТЕРАМ", "home")]
            ]
        }

    def _connector_add_screen(self) -> tuple[str, dict[str, Any]]:
        device_id = str(
            self.registry.get_setting("selected_device", "") or ""
        )
        device = None
        if device_id:
            try:
                device = self.registry.get_device(device_id)
            except KeyError:
                device = None

        connector_id = str(
            self.registry.get_setting(
                "pending_connector_add_id",
                "",
            )
            or ""
        )
        command = str(
            getattr(self, "_pending_connector_install_command", "")
            or ""
        )

        connector = None
        if connector_id:
            try:
                connector = self.registry.get_named_access_connector(
                    connector_id
                )
            except KeyError:
                connector = None

        if connector and int(connector.get("last_seen") or 0):
            self._pending_connector_install_command = ""
            name = self._connector_display_name(connector)
            text = (
                f"{self.icon('success')} УСТРОЙСТВО ГОТОВО\n\n"
                f"{escape(name)} подключено к Bakunity.\n"
                "Теперь Bakunity сможет пробовать прямой P2P, LAN и relay "
                "и выбирать маршрут автоматически."
            )
            keyboard = {
                "inline_keyboard": [
                    [
                        self.button(
                            "settings",
                            "НАСТРОИТЬ УСТРОЙСТВО",
                            f"connection_source:{connector_id}",
                            style="success",
                        )
                    ],
                    [
                        self.button(
                            "back",
                            "НАЗАД",
                            "connector_add_done",
                        )
                    ],
                ]
            }
            return text, keyboard

        if not command:
            text = (
                f"{self.icon('warning')} КОМАНДА БОЛЬШЕ НЕ ПОКАЗЫВАЕТСЯ\n\n"
                "Одноразовый секрет не хранится в базе Bakunity. "
                "Создай новую команду."
            )
            keyboard = {
                "inline_keyboard": [
                    [
                        self.button(
                            "add",
                            "СОЗДАТЬ НОВУЮ КОМАНДУ",
                            "connector_add",
                            style="primary",
                        )
                    ],
                    [
                        self.button(
                            "back",
                            "НАЗАД",
                            "connector_add_cancel",
                        )
                    ],
                ]
            }
            return text, keyboard

        target = (
            f" к {escape(device['display_name'])}"
            if device
            else ""
        )
        text = (
            f"{self.icon('power')} ПРЯМОЕ ПОДКЛЮЧЕНИЕ{target}\n\n"
            "Установи Bakunity на Windows-ПК или ноутбук, "
            "с которого ты обычно подключаешься.\n\n"
            "Это необязательно: без этого RDP продолжит работать "
            "через сервер Bakunity.\n\n"
            "1. Открой PowerShell от администратора.\n"
            "2. Вставь команду целиком.\n"
            "3. Устройство появится здесь автоматически.\n\n"
            f"<pre><code>{html.escape(command)}</code></pre>\n\n"
            "Команда содержит одноразовый секрет. Не пересылай её."
        )
        keyboard = {
            "inline_keyboard": [
                [
                    self.button(
                        "cancel",
                        "ОТМЕНИТЬ",
                        "connector_add_cancel",
                    )
                ]
            ]
        }
        return text, keyboard

    def _connector(
        self,
        connector: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        now = int(time.time())
        last_seen = int(connector.get("last_seen") or 0)
        online = last_seen > 0 and now - last_seen <= 45
        telemetry = connector.get("telemetry") or {}
        native = telemetry.get("native_transport") or {}
        routes = telemetry.get("routes") or {}
        source_name = str(
            connector.get("machine_name")
            or connector.get("name")
            or "Windows"
        )
        native_status = (
            f"{self.icon('success')} В СЕТИ"
            if bool(native.get("online"))
            else f"{self.icon('info')} НЕ ПОДКЛЮЧЁН"
        )

        lines = [
            (
                f"{self.icon('online' if online else 'offline')} "
                f"{escape(source_name).upper()} · "
                f"{'В СЕТИ' if online else 'НЕ В СЕТИ'}"
            ),
            "",
            f"Bakunity Transport: {native_status}",
            "",
            "КОМПЬЮТЕРЫ",
        ]
        rows: list[list[dict[str, Any]]] = []
        for device in self.registry.list_devices():
            route = routes.get(str(device["id"])) or {}
            raw_route = str(route.get("route") or "unavailable")
            latency = int(route.get("latency_ms") or 0)
            policy = self.registry.get_connector_device_route_policy(
                str(connector["id"]),
                str(device["id"]),
            ).upper()
            latency_text = f" · {latency} мс" if latency > 0 else ""
            lines.append(
                f"{escape(device['display_name'])}: "
                f"{escape(self._route_label(raw_route))}"
                f"{latency_text} · {policy}"
            )
            rows.append(
                [
                    self.button(
                        "computer",
                        str(device["display_name"]),
                        f"connection_target:{device['id']}",
                    )
                ]
            )

        if not rows:
            lines.append("Компьютеров пока нет.")

        rows.extend(
            [
                [
                    self.button(
                        "delete",
                        "УДАЛИТЬ УСТРОЙСТВО",
                        f"connector_revoke:{connector['id']}",
                        style="danger",
                    )
                ],
                [
                    self.button("refresh", "ОБНОВИТЬ СТАТУС", "refresh"),
                    self.button(
                        "back",
                        "К УСТРОЙСТВАМ",
                        "connectors",
                    ),
                ],
            ]
        )
        return "\n".join(lines), {"inline_keyboard": rows}

    @staticmethod
    def _route_label(value: str) -> str:
        return {
            "lan": "🏠 LAN",
            "p2p": "⚡ P2P",
            "native_p2p": "⚡ BAKUNITY P2P",
            "native_auto": "⚡ BAKUNITY",
            "native_relay": "☁️ BAKUNITY RELAY",
            "relay": "☁️ ЧЕРЕЗ СЕРВЕР BAKUNITY",
            "unavailable": "⚪ МАРШРУТ ПОКА НЕДОСТУПЕН",
        }.get(str(value or "").lower(), str(value or "—").upper())

    def _device_connection(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        connectors = self._visible_connectors()
        rows: list[list[dict[str, Any]]] = []
        lines = [
            f"{self.icon('power')} ПРЯМОЕ ПОДКЛЮЧЕНИЕ",
            "",
            f"Компьютер: {escape(device['display_name'])}",
            "",
            "Bakunity может подключаться к этому компьютеру напрямую "
            "с другого Windows-устройства.",
            "Это необязательно. Без настройки RDP продолжит работать "
            "через сервер Bakunity.",
            "",
            "МОИ УСТРОЙСТВА",
        ]

        for connector in connectors:
            telemetry = connector.get("telemetry") or {}
            route = (telemetry.get("routes") or {}).get(
                str(device["id"])
            ) or {}
            raw_route = str(route.get("route") or "unavailable")
            try:
                latency = int(route.get("latency_ms") or 0)
            except (TypeError, ValueError):
                latency = 0
            name = self._connector_display_name(connector)
            last_seen = int(connector.get("last_seen") or 0)
            online = last_seen > 0 and int(time.time()) - last_seen <= 45
            route_text = self._route_label(raw_route)
            suffix = f" · {latency} мс" if latency > 0 else ""
            lines.append(
                f"{'🟢' if online else '⚪'} {escape(name)} · "
                f"{escape(route_text)}{suffix}"
            )
            rows.append(
                [
                    self.button(
                        "online" if online else "offline",
                        name,
                        f"connection_source:{connector['id']}",
                        style="success" if online else None,
                    )
                ]
            )

        if not connectors:
            lines.extend(
                [
                    "Пока не настроено.",
                    "",
                    "Добавь устройство только если хочешь прямой P2P/LAN "
                    "и автоматический выбор лучшего маршрута.",
                ]
            )

        rows.append(
            [
                self.button(
                    "add",
                    "ДОБАВИТЬ УСТРОЙСТВО",
                    "connector_add",
                    style="primary",
                )
            ]
        )
        rows.append(
            [
                self.button(
                    "back",
                    "К НАСТРОЙКАМ",
                    f"settings:{device['id']}",
                )
            ]
        )
        return "\n".join(lines), {"inline_keyboard": rows}

    def _device_connection_source(
        self,
        device: dict[str, Any],
        connector: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        telemetry = connector.get("telemetry") or {}
        route = (telemetry.get("routes") or {}).get(
            str(device["id"])
        ) or {}
        raw_route = str(route.get("route") or "unavailable")
        try:
            latency = int(route.get("latency_ms") or 0)
        except (TypeError, ValueError):
            latency = 0
        try:
            active_sessions = int(route.get("active_sessions") or 0)
        except (TypeError, ValueError):
            active_sessions = 0
        policy = self.registry.get_connector_device_route_policy(
            str(connector["id"]),
            str(device["id"]),
        )
        source_name = self._connector_display_name(connector)
        machine = str(connector.get("machine_name") or "").strip()
        latency_text = f" · {latency} мс" if latency > 0 else ""
        if active_sessions > 0:
            current = (
                f"Сейчас: {escape(self._route_label(raw_route))}"
                f"{latency_text}"
            )
        else:
            current = "Сейчас: ⚪ подключение не активно"

        text = (
            f"{self.icon('settings')} {escape(source_name).upper()}\n\n"
            f"Windows: {escape(machine or '—')}\n"
            f"Куда: {escape(device['display_name'])}\n\n"
            f"{current}\n"
            f"Доступный маршрут: {escape(self._route_label(raw_route))}"
            f"{latency_text}\n"
            f"Режим: {escape(self._policy_label(policy))}\n\n"
            "АВТО — рекомендуемый режим: Bakunity сначала пробует LAN "
            "и прямой P2P, а при необходимости использует relay."
        )

        buttons = [
            [
                self.button(
                    "success" if policy == "auto" else "info",
                    "АВТО",
                    "route_pair:auto",
                ),
                self.button(
                    "success" if policy == "p2p" else "info",
                    "P2P",
                    "route_pair:p2p",
                ),
            ],
            [
                self.button(
                    "success" if policy == "lan" else "info",
                    "LAN",
                    "route_pair:lan",
                ),
                self.button(
                    "success" if policy == "relay" else "info",
                    "RELAY",
                    "route_pair:relay",
                ),
            ],
            [
                self.button(
                    "edit",
                    "ИЗМЕНИТЬ ИМЯ",
                    f"edit_connector:{connector['id']}",
                )
            ],
            [
                self.button(
                    "delete",
                    "УДАЛИТЬ УСТРОЙСТВО",
                    f"connector_revoke:{connector['id']}",
                    style="danger",
                )
            ],
            [
                self.button(
                    "back",
                    "НАЗАД",
                    f"connection:{device['id']}",
                )
            ],
        ]
        return text, {"inline_keyboard": buttons}

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

    def _device_settings(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        connectors = self._visible_connectors()
        count = len(connectors)
        direct_status = (
            f"настроено устройств: {count}"
            if count
            else "не настроено"
        )
        text = (
            f"{self.icon('settings')} "
            f"{escape(device['display_name']).upper()} · НАСТРОЙКИ\n\n"
            f"Имя: {escape(device['display_name'])}\n"
            f"RDP-адрес: {escape(self._product_rdp_endpoint(device))}\n"
            f"Прямое подключение: {direct_status}\n\n"
            "Маршрут для каждого устройства по умолчанию — АВТО. "
            "Его можно изменить внутри прямого подключения."
        )
        keyboard = {
            "inline_keyboard": [
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
                    self.button(
                        "power",
                        "ПРЯМОЕ ПОДКЛЮЧЕНИЕ",
                        f"connection:{device['id']}",
                        style="primary",
                    )
                ],
                [
                    self.button(
                        "back",
                        "К КОМПЬЮТЕРУ",
                        f"device:{device['id']}",
                    )
                ],
            ]
        }
        return text, keyboard

    def _connector_edit(
        self,
        connector: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        error = str(self.registry.get_setting("input_error", "") or "")
        current = self._connector_display_name(connector)
        error_text = (
            f"\n\n{self.icon('warning')} Ошибка: {escape(error)}"
            if error
            else ""
        )
        text = (
            f"{self.icon('edit')} ИЗМЕНИТЬ ИМЯ УСТРОЙСТВА\n\n"
            f"Сейчас: {escape(current)}\n\n"
            "Отправь новое имя одним сообщением. "
            "Например: Рабочий ноутбук.\n\n"
            "После сохранения сообщение будет удалено из чата."
            f"{error_text}"
        )
        return text, {
            "inline_keyboard": [
                [
                    self.button(
                        "cancel",
                        "ОТМЕНА",
                        f"connector_edit_cancel:{connector['id']}",
                    )
                ]
            ]
        }

    def _device(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        online = self._online(device)
        telemetry = device.get("telemetry") or {}
        desired_access = bool(device.get("enabled", True))
        pending_action = str(device.get("pending_command") or "")
        notice = self._product_notice(device)
        connection = self._active_connection_state(device)

        connection_lines = [
            "ПОДКЛЮЧЕНИЕ",
            (
                f"{self.icon('online')} Доступ включён"
                if desired_access
                else f"{self.icon('offline')} Доступ выключен"
            ),
            str(connection["label"]),
        ]
        if connection["active"] and int(connection["latency_ms"] or 0) > 0:
            connection_lines[-1] += (
                f" · {int(connection['latency_ms'])} мс"
            )
        if connection["active"] and connection["source"]:
            connection_lines.append(
                f"Откуда: {escape(connection['source'])}"
            )
        if (
            connection["active"]
            and connection["exact"]
            and (
                int(connection["bytes_received"] or 0) > 0
                or int(connection["bytes_sent"] or 0) > 0
            )
        ):
            connection_lines.extend(
                [
                    "",
                    "Трафик сессии:",
                    (
                        f"↓ {format_bytes(connection['bytes_received'])}   "
                        f"↑ {format_bytes(connection['bytes_sent'])}"
                    ),
                ]
            )
        if (
            connection["active"]
            and connection["exact"]
            and int(connection["sessions"] or 0) > 0
        ):
            connection_lines.append(
                f"RDP-сессий: {int(connection['sessions'])}"
            )

        notice_text = f"\n\n{notice}" if notice else ""
        text = (
            f"{self.icon('online' if online else 'offline')} "
            f"{escape(device['display_name']).upper()} · "
            f"{'В СЕТИ' if online else 'НЕ В СЕТИ'}\n\n"
            f"{escape(telemetry.get('os', '—'))}\n"
            f"Адрес: {escape(self._product_rdp_endpoint(device))}\n\n"
            + "\n".join(connection_lines)
            + notice_text
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
                ]
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
                        "settings",
                        "НАСТРОЙКИ",
                        f"settings:{device['id']}",
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
                        "back",
                        "К КОМПЬЮТЕРАМ",
                        "home",
                    )
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
                        "ОБНОВИТЬ СТАТУС",
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
                        "ОБНОВИТЬ СТАТУС",
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
        connection = self._active_connection_state(device)
        cpu = float(telemetry.get("cpu_percent", 0) or 0)
        ram = float(telemetry.get("ram_percent", 0) or 0)
        disk = float(telemetry.get("disk_percent", 0) or 0)
        sessions = telemetry.get("sessions") or []
        session_text = escape(", ".join(sessions) or "нет")

        route_line = str(connection["label"])
        if connection["active"] and int(connection["latency_ms"] or 0) > 0:
            route_line += f" · {int(connection['latency_ms'])} мс"

        traffic = ""
        if (
            connection["active"]
            and connection["exact"]
            and (
                int(connection["bytes_received"] or 0) > 0
                or int(connection["bytes_sent"] or 0) > 0
            )
        ):
            traffic = (
                f"\nТрафик сессии: "
                f"↓ {format_bytes(connection['bytes_received'])} · "
                f"↑ {format_bytes(connection['bytes_sent'])}"
            )

        session_line = (
            f"\nRDP-сессий: {int(connection['sessions'])}"
            if connection["active"]
            else ""
        )

        certificate_ok = telemetry.get("certificate_lifecycle_ok")
        if certificate_ok is True:
            certificate = f"{self.icon('success')} готов"
        elif certificate_ok is False:
            certificate = f"{self.icon('warning')} требует восстановления"
        else:
            certificate = "—"

        ssh_running = bool(telemetry.get("ssh_tunnel_running"))
        try:
            ssh_count = int(telemetry.get("ssh_process_count") or 0)
        except (TypeError, ValueError):
            ssh_count = 0
        fallback = (
            f"{self.icon('success')} готов"
            if ssh_running and ssh_count == 1
            else f"{self.icon('info')} —"
        )

        update_status = self._update_status_text(device)
        text = (
            f"{self.icon('info')} "
            f"{escape(device['display_name']).upper()} · ПОДРОБНЕЕ\n\n"
            "ПОДКЛЮЧЕНИЕ\n"
            f"{route_line}"
            f"{session_line}"
            f"{traffic}\n\n"
            "СИСТЕМА\n"
            f"Пользователь: {escape(telemetry.get('interactive_user') or session_text)}\n"
            f"Сессии Windows: {session_text}\n"
            f"Аптайм: {format_duration(telemetry.get('uptime_seconds'))}\n\n"
            f"CPU: {cpu:.1f}%\n{bar(cpu)}\n\n"
            f"RAM: {ram:.1f}%\n{bar(ram)}\n"
            f"{format_bytes(telemetry.get('ram_used_bytes'))} / "
            f"{format_bytes(telemetry.get('ram_total_bytes'))}\n\n"
            f"Диск C: {disk:.1f}%\n{bar(disk)}\n"
            f"{format_bytes(telemetry.get('disk_used_bytes'))} / "
            f"{format_bytes(telemetry.get('disk_total_bytes'))}\n\n"
            "BAKUNITY RDP\n"
            f"Агент: {self.icon('online' if self._online(device) else 'offline')} "
            f"{'работает' if self._online(device) else 'не в сети'}\n"
            f"Сертификат: {certificate}\n"
            f"Резервное подключение: {fallback}\n"
            f"Резервный адрес: {escape(self._rdp_endpoint(device))}\n"
            f"{update_status}"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    self.button(
                        "repeat",
                        "ПЕРЕЗАПУСТИТЬ ПОДКЛЮЧЕНИЕ",
                        f"cmd:restart:{device['id']}",
                        style="primary",
                    )
                ],
                [
                    self.button(
                        "repair",
                        "ВОССТАНОВИТЬ",
                        f"repair:{device['id']}",
                    )
                ],
                [
                    self.button(
                        "delete",
                        "УДАЛИТЬ КОМПЬЮТЕР",
                        f"delete:{device['id']}",
                        style="danger",
                    )
                ],
                [
                    self.button("refresh", "ОБНОВИТЬ СТАТУС", "refresh"),
                    self.button(
                        "back",
                        "НАЗАД",
                        f"device:{device['id']}",
                    ),
                ],
            ]
        }
        return text[:4000], keyboard

    def _device_technical(
        self,
        device: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        # Legacy callback compatibility: V2 has one unified Details screen.
        return self._device_details(device)

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
        if screen == "device_connection":
            device_id = self.registry.get_setting(
                "selected_device",
                "",
            ) or ""
            try:
                return self._device_connection(
                    self.registry.get_device(device_id)
                )
            except KeyError:
                self.registry.set_setting("screen", "home")
                return self._home()
        if screen == "device_connection_source":
            device_id = self.registry.get_setting(
                "selected_device",
                "",
            ) or ""
            connector_id = self.registry.get_setting(
                "selected_connector",
                "",
            ) or ""
            try:
                return self._device_connection_source(
                    self.registry.get_device(device_id),
                    self.registry.get_named_access_connector(connector_id),
                )
            except KeyError:
                self.registry.set_setting("screen", "device_connection")
                return self._device_connection(
                    self.registry.get_device(device_id)
                )
        if screen == "connector_edit":
            connector_id = self.registry.get_setting(
                "selected_connector",
                "",
            ) or ""
            try:
                return self._connector_edit(
                    self.registry.get_named_access_connector(connector_id)
                )
            except KeyError:
                self.registry.set_setting("screen", "device_connection")
                device_id = self.registry.get_setting(
                    "selected_device",
                    "",
                ) or ""
                return self._device_connection(
                    self.registry.get_device(device_id)
                )
        if screen == "connector_add":
            return self._connector_add_screen()
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
                self.registry.set_setting("screen", "home")
                return self._home()
            return self._connector(connector)
        if screen in {
            "repair",
            "device_details",
            "device_technical",
            "device_settings",
            "device_edit",
            "device_address_progress",
        }:
            device_id = self.registry.get_setting(
                "selected_device",
                "",
            ) or ""
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
            if screen == "device_settings":
                return self._device_settings(device)
            if screen == "device_technical":
                return self._device_details(device)
            if screen == "device_address_progress":
                return self._device_address_progress(device)
            return self._device_details(device)
        return super()._render_content()

