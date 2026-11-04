from __future__ import annotations

import html
import json
import logging
import math
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .config import Config
from .db import Registry
from .tunnel import close_tunnel
from .telegram_icons import APPROVED_PACKS, TelegramEmojiTheme


LOG = logging.getLogger("hermes_rdp.bot")
LIVE_SECONDS = 60


def escape(value: Any) -> str:
    return str(value).replace("<", "‹").replace(">", "›").replace("&", "＆")


def bar(percent: float) -> str:
    value = max(0.0, min(100.0, float(percent)))
    filled = int(round(value / 10.0))
    return "▓" * filled + "░" * (10 - filled)


def format_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1
    return f"{number:.2f} {units[index]}"


def format_duration(seconds: Any) -> str:
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return "—"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}д {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class TelegramBot:
    def __init__(self, config: Config, registry: Registry):
        self.config = config
        self.registry = registry
        self.api = f"https://api.telegram.org/bot{config.telegram_token}"
        self.stop_event = threading.Event()
        self.offset = 0
        self.lock = threading.RLock()
        self.last_render = 0.0
        self.last_device_signature: tuple[Any, ...] | None = None
        self.emoji = TelegramEmojiTheme()
        self._emoji_packs_loaded = False

    def api_call(self, method: str, payload: dict[str, Any] | None = None, timeout: int = 40):
        request = urllib.request.Request(
            f"{self.api}/{method}",
            data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(body or str(exc)) from exc
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "Telegram API error"))
        return result.get("result")

    def _load_emoji_packs(self) -> None:
        if getattr(self, "_emoji_packs_loaded", False):
            return
        self._emoji_packs_loaded = True
        theme = self._emoji_theme()

        loaded_sets: dict[str, dict[str, Any]] = {}
        loaded_pack_names: dict[str, str] = {}
        membership: dict[str, str] = {}

        for pack_name in APPROVED_PACKS:
            try:
                sticker_set = self.api_call(
                    "getStickerSet",
                    {"name": pack_name},
                    timeout=15,
                )
            except Exception as exc:
                LOG.debug("custom emoji pack %s unavailable: %s", pack_name, exc)
                continue

            if not isinstance(sticker_set, dict):
                continue
            actual_name = str(sticker_set.get("name") or pack_name)
            loaded_sets[pack_name] = sticker_set
            loaded_pack_names[pack_name] = actual_name
            for sticker in sticker_set.get("stickers") or []:
                if not isinstance(sticker, dict):
                    continue
                custom_id = str(sticker.get("custom_emoji_id") or "")
                if custom_id:
                    membership[custom_id] = actual_name

        # Verify that the curated IDs exist. set_name on Sticker is optional in
        # Bot API, so existence is checked separately from set membership.
        curated_ids = [
            custom_id
            for custom_id, _ in theme.pinned_ids().values()
        ]
        existing_ids: set[str] = set()
        if curated_ids:
            try:
                stickers = self.api_call(
                    "getCustomEmojiStickers",
                    {"custom_emoji_ids": curated_ids[:200]},
                    timeout=15,
                ) or []
                for sticker in stickers:
                    if isinstance(sticker, dict):
                        custom_id = str(sticker.get("custom_emoji_id") or "")
                        if custom_id:
                            existing_ids.add(custom_id)
            except Exception as exc:
                LOG.debug("custom emoji existence validation failed: %s", exc)

        invalidated = theme.reconcile_pack_membership(
            membership,
            loaded_pack_names,
        )
        if invalidated:
            LOG.info(
                "Discarded %s custom emoji IDs that do not belong to the selected packs",
                invalidated,
            )

        # Re-discover any invalidated icons from the exact selected sets.
        for pack_name, sticker_set in loaded_sets.items():
            theme.learn_pack(pack_name, sticker_set)

        missing_existing = [
            custom_id
            for custom_id, _ in theme.pinned_ids().values()
            if existing_ids and custom_id not in existing_ids
        ]
        if missing_existing:
            LOG.info(
                "Telegram did not confirm %s resolved custom emoji IDs",
                len(missing_existing),
            )

        LOG.info(
            "Telegram emoji theme resolved %s/%s icons from packs: %s",
            theme.resolved_count(),
            len(theme.icons),
            ", ".join(theme.resolved_packs()) or "none",
        )

    def _emoji_theme(self) -> TelegramEmojiTheme:
        theme = getattr(self, "emoji", None)
        if theme is None:
            theme = TelegramEmojiTheme()
            self.emoji = theme
        return theme

    def icon(self, name: str) -> str:
        return self._emoji_theme().html(name)

    def button(
        self,
        icon: str,
        text: str,
        callback_data: str,
        *,
        style: str | None = None,
    ) -> dict[str, Any]:
        return self._emoji_theme().button(
            icon,
            text,
            callback_data=callback_data,
            style=style,
        )

    @staticmethod
    def _is_custom_emoji_error(exc: Exception) -> bool:
        value = str(exc).lower()
        return any(
            marker in value
            for marker in (
                "custom emoji",
                "custom_emoji",
                "icon_custom",
                "premium",
            )
        )

    def _render_api_call(
        self,
        method: str,
        payload: dict[str, Any],
    ) -> Any:
        try:
            return self.api_call(method, payload)
        except Exception as exc:
            theme = self._emoji_theme()
            if not (
                theme.enabled
                and theme.payload_has_custom_emoji(payload)
                and self._is_custom_emoji_error(exc)
            ):
                raise

            # A button icon failure must not wipe custom emoji from the whole
            # dashboard. First retry with only button custom icons disabled.
            if (
                theme.buttons_enabled
                and theme.payload_has_button_custom_emoji(payload)
            ):
                LOG.info(
                    "Telegram rejected button custom emoji; retrying with text custom emoji intact: %s",
                    exc,
                )
                theme.buttons_enabled = False
                text, keyboard = self._render_content()
                retry_payload = dict(payload)
                retry_payload["text"] = text
                retry_payload["reply_markup"] = keyboard
                try:
                    return self.api_call(method, retry_payload)
                except Exception as retry_exc:
                    if not (
                        theme.text_enabled
                        and theme.payload_has_text_custom_emoji(retry_payload)
                        and self._is_custom_emoji_error(retry_exc)
                    ):
                        raise

                    LOG.info(
                        "Telegram also rejected text custom emoji; falling back to Unicode: %s",
                        retry_exc,
                    )
                    theme.text_enabled = False
                    text, keyboard = self._render_content()
                    unicode_payload = dict(payload)
                    unicode_payload["text"] = text
                    unicode_payload["reply_markup"] = keyboard
                    return self.api_call(method, unicode_payload)

            if (
                theme.text_enabled
                and theme.payload_has_text_custom_emoji(payload)
            ):
                LOG.info(
                    "Telegram rejected text custom emoji; falling back to Unicode text only: %s",
                    exc,
                )
                theme.text_enabled = False
                text, keyboard = self._render_content()
                retry_payload = dict(payload)
                retry_payload["text"] = text
                retry_payload["reply_markup"] = keyboard
                return self.api_call(method, retry_payload)

            raise

    def run(self) -> None:
        self.api_call("deleteWebhook", {"drop_pending_updates": False})
        self._load_emoji_packs()
        updater = threading.Thread(target=self._live_loop, daemon=True)
        updater.start()
        failures = 0
        while not self.stop_event.is_set():
            try:
                updates = self.api_call(
                    "getUpdates",
                    {
                        "offset": self.offset,
                        "timeout": 30,
                        "allowed_updates": ["message", "callback_query"],
                    },
                    timeout=40,
                )
                failures = 0
                for update in updates:
                    self.offset = int(update["update_id"]) + 1
                    self._handle_update(update)
                self.registry.cleanup()
            except Exception as exc:
                failures += 1
                delay = min(60, 5 * (2 ** min(failures - 1, 4)))
                LOG.warning("Telegram loop error: %s; retry in %ss", exc, delay)
                self.stop_event.wait(delay)

    def stop(self) -> None:
        self.stop_event.set()

    def _authorized(self, update: dict[str, Any]) -> bool:
        message = update.get("message") or update.get("callback_query", {}).get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        actor_id = str(
            update.get("callback_query", {}).get("from", {}).get("id", "")
            or message.get("from", {}).get("id", "")
        )
        return chat_id == self.config.telegram_chat_id and actor_id == self.config.telegram_chat_id

    def _live_until(self) -> int:
        try:
            return int(self.registry.get_setting("live_until", "0") or 0)
        except (TypeError, ValueError):
            return 0

    def _live_remaining(self) -> int:
        return max(0, self._live_until() - int(time.time()))

    def _live_active(self) -> bool:
        return self._live_remaining() > 0

    def _set_live(self, enabled: bool) -> None:
        if enabled:
            self.registry.set_setting("live_until", str(int(time.time()) + LIVE_SECONDS))
        else:
            self.registry.set_setting("live_until", "0")

    def _handle_update(self, update: dict[str, Any]) -> None:
        if not self._authorized(update):
            callback = update.get("callback_query")
            if callback:
                self._answer(callback.get("id", ""), "Нет доступа")
            return
        if "message" in update:
            text = str(update["message"].get("text", "")).split("@", 1)[0].lower()
            if text in {"/start", "/menu", "/status"}:
                self._set_live(False)
                self.registry.set_setting("screen", "home")
                self.registry.set_setting("selected_device", "")
                self.render(force_new=True)
            return
        callback = update.get("callback_query")
        if callback:
            self._handle_callback(callback)

    def _answer(self, callback_id: str, text: str = "") -> None:
        try:
            payload = {"callback_query_id": callback_id}
            if text:
                payload["text"] = text[:180]
            self.api_call("answerCallbackQuery", payload, timeout=15)
        except Exception as exc:
            LOG.debug("callback answer failed: %s", exc)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        data = str(callback.get("data", "home"))
        callback_id = str(callback.get("id", ""))
        if data == "home":
            self._set_live(False)
            self.registry.set_setting("screen", "home")
            self.registry.set_setting("selected_device", "")
            self._answer(callback_id)
            self.render()
            return
        if data == "add":
            self._set_live(False)
            code = self.registry.create_pair_code(ttl_seconds=self.config.pair_ttl_seconds)
            self.registry.set_setting("pair_code", code)
            self.registry.set_setting("screen", "pair")
            self._answer(callback_id, "Код создан")
            self.render()
            return
        if data == "refresh":
            self._answer(callback_id, "Обновлено")
            self.render()
            return
        if data == "live":
            enabled = not self._live_active()
            self._set_live(enabled)
            self._answer(
                callback_id,
                "Наблюдение включено на 60 секунд"
                if enabled
                else "Наблюдение остановлено",
            )
            self.render()
            return
        if data.startswith("device:"):
            device_id = data.split(":", 1)[1]
            try:
                self.registry.get_device(device_id)
            except KeyError:
                self._answer(callback_id, "Устройство не найдено")
                self.render()
                return
            self._set_live(False)
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "device")
            self._answer(callback_id)
            self.render()
            return
        if data.startswith("cmd:"):
            _, action, device_id = data.split(":", 2)
            try:
                device = self.registry.get_device(device_id)
                self.registry.queue_command(device_id, action)
                if action == "off":
                    try:
                        close_tunnel(self.config, int(device["rdp_port"]))
                    except Exception as exc:
                        LOG.warning("tunnel close failed: %s", exc)
                self._answer(callback_id, f"Команда {action.upper()} отправлена")
            except Exception as exc:
                self._answer(callback_id, str(exc))
            self.render()
            return
        if data.startswith("delete:"):
            self._set_live(False)
            device_id = data.split(":", 1)[1]
            self.registry.set_setting("selected_device", device_id)
            self.registry.set_setting("screen", "delete")
            self._answer(callback_id)
            self.render()
            return
        if data.startswith("delete_yes:"):
            self._set_live(False)
            device_id = data.split(":", 1)[1]
            try:
                device = self.registry.get_device(device_id)
                self.registry.revoke_device(device_id)
                try:
                    close_tunnel(self.config, int(device["rdp_port"]))
                except Exception as exc:
                    LOG.warning("deleted tunnel close failed: %s", exc)
                self._answer(callback_id, "Устройство удалено")
            except Exception as exc:
                self._answer(callback_id, str(exc))
            self.registry.set_setting("screen", "home")
            self.registry.set_setting("selected_device", "")
            self.render()
            return
        self._answer(callback_id)

    def _device_signature(self) -> tuple[Any, ...] | None:
        if self.registry.get_setting("screen", "home") not in {"device", "device_details"}:
            return None
        device_id = self.registry.get_setting("selected_device", "") or ""
        if not device_id:
            return None
        try:
            device = self.registry.get_device(device_id)
        except KeyError:
            return None

        telemetry = device.get("telemetry") or {}
        last_result = device.get("last_result") or {}
        return (
            device_id,
            bool(device.get("enabled", True)),
            str(device.get("pending_command") or ""),
            int(device.get("command_seq") or 0),
            int(last_result.get("seq") or 0),
            bool(last_result.get("ok")) if last_result else None,
            str(last_result.get("status") or ""),
            str(last_result.get("action") or ""),
            self._online(device),
            telemetry.get("access_enabled"),
            telemetry.get("ssh_tunnel_running"),
            telemetry.get("ssh_process_count"),
            telemetry.get("endpoint_available"),
            telemetry.get("client_repository_ref"),
            telemetry.get("maintenance_capable"),
            telemetry.get("certificate_lifecycle_ok"),
            str((telemetry.get("maintenance_status") or {}).get("state") or ""),
            str((telemetry.get("maintenance_status") or {}).get("action") or ""),
            bool((telemetry.get("maintenance_status") or {}).get("ok")),
        )

    def _live_loop(self) -> None:
        was_active = False
        while not self.stop_event.wait(3):
            try:
                screen = self.registry.get_setting("screen", "home")
                if screen not in {"device", "device_details"}:
                    self.last_device_signature = None
                    was_active = False
                    continue

                active = self._live_active()
                if active:
                    self.render()
                    was_active = True
                    continue

                if was_active:
                    was_active = False
                    self.render()
                    continue

                signature = self._device_signature()
                if signature != self.last_device_signature:
                    self.render()
            except Exception as exc:
                LOG.debug("live render failed: %s", exc)

    def _online(self, device: dict[str, Any]) -> bool:
        last_seen = int(device.get("last_seen") or 0)
        return last_seen > 0 and int(time.time()) - last_seen <= self.config.online_after_seconds

    def _home(self) -> tuple[str, dict[str, Any]]:
        devices = self.registry.list_devices()
        online = sum(1 for device in devices if self._online(device))
        text = (
            f"{self.icon('computer')} BAKUNITY RDP · КОМПЬЮТЕРЫ\n\n"
            f"Онлайн: {online} из {len(devices)}\n"
            f"OpenSSH-туннели: порт {self.config.ssh_bind_port}\n"
            f"Диапазон RDP: {self.config.port_start}–{self.config.port_end}\n"
            f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        )
        rows = []
        for device in devices:
            rows.append(
                [
                    self.button(
                        "success" if self._online(device) else "cancel",
                        f"{device['display_name']} · :{device['rdp_port']}",
                        f"device:{device['id']}",
                        style="success" if self._online(device) else "danger",
                    )
                ]
            )
        rows.append([self.button("add", "ДОБАВИТЬ ПК", "add", style="primary")])
        rows.append([self.button("refresh", "ОБНОВИТЬ", "refresh")])
        return text, {"inline_keyboard": rows}

    def _pair(self) -> tuple[str, dict[str, Any]]:
        code = self.registry.get_setting("pair_code", "") or ""
        command = (
            "$u='" + self.config.client_installer_url + "'\n"
            "$s=(irm $u).TrimStart([char]0xFEFF)\n"
            "$p=@{\n"
            f"  Server='{self.config.public_host}'\n"
            f"  PairCode='{code}'\n"
            f"  Fingerprint='{self.config.tls_fingerprint}'\n"
            f"  RepositoryRef='{self.config.repository_ref}'\n"
            "}\n"
            "& ([scriptblock]::Create($s)) @p"
        )
        text = (
            f"{self.icon('add')} ДОБАВЛЕНИЕ WINDOWS-ПК\n\n"
            f"Код: {code}\n"
            f"Действует: {self.config.pair_ttl_seconds // 60} минут\n\n"
            "1. Открой PowerShell от администратора на новом ПК.\n"
            "2. Вставь команду ниже.\n"
            "3. Установщик спросит удобное название компьютера.\n\n"
            f"<pre><code>{html.escape(command)}</code></pre>"
        )
        keyboard = {"inline_keyboard": [[self.button("back", "К СПИСКУ", "home")]]}
        return text, keyboard

    def _device(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        online = self._online(device)
        telemetry = device.get("telemetry") or {}
        now = int(time.time())
        age = max(0, now - int(device.get("last_seen") or 0)) if device.get("last_seen") else None
        try:
            resource_age = max(0, now - int(telemetry.get("resource_captured_at") or 0))
        except (TypeError, ValueError):
            resource_age = None
        if not telemetry.get("resource_captured_at"):
            resource_age = None

        cpu = float(telemetry.get("cpu_percent", 0) or 0)
        ram = float(telemetry.get("ram_percent", 0) or 0)
        disk = float(telemetry.get("disk_percent", 0) or 0)
        sessions = telemetry.get("sessions") or []
        user = telemetry.get("interactive_user") or (sessions[0] if sessions else "нет")
        live_remaining = self._live_remaining()
        live_active = live_remaining > 0

        process_lines = []
        process_status = "Наблюдение выключено."
        if live_active:
            processes = telemetry.get("top_processes") or []
            try:
                process_age = max(
                    0,
                    now - int(telemetry.get("top_processes_captured_at") or 0),
                )
            except (TypeError, ValueError):
                process_age = None
            if processes:
                process_status = (
                    f"Наблюдение: {self.icon('success')} ещё {live_remaining} сек."
                    + (f" · снимок {process_age} сек. назад" if process_age is not None else "")
                )
                for index, process in enumerate(processes[:5], 1):
                    process_lines.append(
                        f"{index}. {escape(process.get('name', '?'))} · "
                        f"{process.get('cpu_percent', 0)}% · "
                        f"{format_bytes(process.get('memory_bytes', 0))} · "
                        f"PID {process.get('pid', '?')}"
                    )
            else:
                process_status = f"Наблюдение: {self.icon('success')} ещё {live_remaining} сек. · ждём первый снимок"

        desired_access = bool(device.get("enabled", True))
        if online and "access_enabled" in telemetry:
            applied_access = (
                f"{self.icon('success')} ВКЛЮЧЕН"
                if bool(telemetry["access_enabled"])
                else f"{self.icon('access_off')} ВЫКЛЮЧЕН"
            )
        else:
            applied_access = f"{self.icon('info')} НЕИЗВЕСТНО"

        ssh_status = f"{self.icon('info')} НЕИЗВЕСТНО"
        if online and "ssh_tunnel_running" in telemetry and "ssh_process_count" in telemetry:
            try:
                ssh_process_count = int(telemetry.get("ssh_process_count") or 0)
            except (TypeError, ValueError):
                ssh_process_count = -1
            ssh_running = bool(telemetry.get("ssh_tunnel_running"))
            if ssh_process_count > 1:
                ssh_status = f"{self.icon('warning')} ДУБЛИ ({ssh_process_count})"
            elif ssh_running and ssh_process_count == 1:
                ssh_status = f"{self.icon('success')} ПОДКЛЮЧЕН"
            elif not ssh_running and ssh_process_count == 0:
                ssh_status = f"{self.icon('access_off')} ОТКЛЮЧЕН"
            else:
                ssh_status = f"{self.icon('warning')} НЕСООТВЕТСТВИЕ"

        if online and "endpoint_available" in telemetry:
            endpoint_status = (
                f"{self.icon('success')} ОТКРЫТ"
                if bool(telemetry["endpoint_available"])
                else f"{self.icon('access_off')} ЗАКРЫТ"
            )
        else:
            endpoint_status = f"{self.icon('info')} НЕИЗВЕСТНО"

        if online and "rdp_hermes_connections" in telemetry:
            rdp_hermes_connections = str(
                int(telemetry.get("rdp_hermes_connections", 0) or 0)
            )
        else:
            rdp_hermes_connections = "НЕИЗВЕСТНО"

        if online and "rdp_direct_connections" in telemetry:
            rdp_direct_connections = str(
                int(telemetry.get("rdp_direct_connections", 0) or 0)
            )
        else:
            rdp_direct_connections = "НЕИЗВЕСТНО"

        rdp_other_line = ""
        if online and "rdp_other_local_connections" in telemetry:
            rdp_other_connections = int(
                telemetry.get("rdp_other_local_connections", 0) or 0
            )
            if rdp_other_connections > 0:
                rdp_other_line = f"RDP локально (другое): {rdp_other_connections}\n"

        pending_action = str(device.get("pending_command") or "")
        last_result = device.get("last_result") or {}
        action_names = {
            "on": "включение доступа",
            "off": "выключение доступа",
            "restart": "перезапуск туннеля",
            "repair": "восстановление клиента",
            "update": "обновление клиента",
        }
        if pending_action:
            command_line = f"{self.icon('timer')} Команда: " + action_names.get(pending_action, pending_action) + "…"
        elif last_result:
            result_icon = self.icon("success" if last_result.get("ok") else "cancel")
            result_action = action_names.get(
                str(last_result.get("action") or ""),
                "последняя команда",
            )
            command_line = f"{result_icon} Последняя команда: {result_action}"
            if not last_result.get("ok") and last_result.get("message"):
                command_line += f" · {escape(last_result['message'])}"
        else:
            command_line = "Последняя команда: —"

        maintenance_capable = bool(telemetry.get("maintenance_capable"))
        client_ref = str(telemetry.get("client_repository_ref") or "").lower()
        desired_ref = str(getattr(self.config, "repository_ref", "") or "").lower()
        if maintenance_capable:
            if client_ref and client_ref == desired_ref:
                client_status = f"{self.icon('success')} АКТУАЛЕН · {client_ref[:7]}"
            elif client_ref and desired_ref:
                client_status = f"{self.icon('upload')} ОБНОВЛЕНИЕ · {client_ref[:7]} → {desired_ref[:7]}"
            else:
                client_status = f"{self.icon('warning')} REF НЕИЗВЕСТЕН"
        else:
            client_status = f"{self.icon('info')} LEGACY · нужен один ручной Repair"

        if (
            bool(getattr(self.config, "trusted_rdp_certificate_enabled", False))
            and online
            and "certificate_lifecycle_ok" in telemetry
        ):
            certificate_status = (
                f"{self.icon('shield')} MANAGED"
                if bool(telemetry.get("certificate_lifecycle_ok"))
                else f"{self.icon('warning')} SELF-HEAL НУЖЕН"
            )
        else:
            certificate_status = f"{self.icon('info')} НЕИЗВЕСТНО"

        maintenance = telemetry.get("maintenance_status") or {}
        maintenance_state = str(maintenance.get("state") or "")
        maintenance_action = str(maintenance.get("action") or "")
        if maintenance_state == "running":
            maintenance_line = f"{self.icon('timer')} {maintenance_action.upper()}"
        elif maintenance_state == "failed":
            maintenance_line = f"{self.icon('cancel')} {maintenance_action.upper()}"
        elif maintenance_state == "completed" and maintenance.get("ok"):
            maintenance_line = f"{self.icon('success')} {maintenance_action.upper()}"
        else:
            maintenance_line = "—"

        resource_line = (
            f"Ресурсы: {resource_age} сек. назад\n"
            if resource_age is not None
            else "Ресурсы: ещё не поступили\n"
        )
        process_body = "\n".join(process_lines) if process_lines else "—"

        text = (
            f"{self.icon('success' if online else 'cancel')} {escape(device['display_name']).upper()} · "
            f"{'В СЕТИ' if online else 'НЕ В СЕТИ'}\n\n"
            f"Компьютер: {escape(device['machine_name'])}\n"
            f"Система: {escape(telemetry.get('os', '—'))}\n"
            f"Пользователь: {escape(user)}\n"
            f"Данные: {str(age) + ' сек. назад' if age is not None else 'ещё не поступили'}\n"
            f"{resource_line}"
            f"RDP: {self.config.public_host}:{device['rdp_port']}\n\n"
            f"CPU: {cpu:.1f}%\n{bar(cpu)}\n\n"
            f"RAM: {ram:.1f}%\n{bar(ram)}\n"
            f"{format_bytes(telemetry.get('ram_used_bytes'))} / {format_bytes(telemetry.get('ram_total_bytes'))}\n\n"
            f"Диск C: {disk:.1f}%\n{bar(disk)}\n"
            f"{format_bytes(telemetry.get('disk_used_bytes'))} / {format_bytes(telemetry.get('disk_total_bytes'))}\n\n"
            "Сеть после запуска Windows\n"
            f"{self.icon('download')} Получено: {format_bytes(telemetry.get('network_received_bytes'))}\n"
            f"{self.icon('upload')} Отправлено: {format_bytes(telemetry.get('network_sent_bytes'))}\n"
            f"Маршрут: {escape(telemetry.get('route', '—'))}\n\n"
            "СОСТОЯНИЕ\n"
            f"Агент: {self.icon('success' if online else 'cancel')} {'В СЕТИ' if online else 'НЕ В СЕТИ'}\n"
            f"Клиент: {client_status}\n"
            f"Сертификат: {certificate_status}\n"
            f"Maintenance: {maintenance_line}\n"
            f"RDP-доступ (цель): {self.icon('access_on' if desired_access else 'access_off')} {'ВКЛЮЧЕН' if desired_access else 'ВЫКЛЮЧЕН'}\n"
            f"Агент применил: {applied_access}\n"
            f"SSH-туннель: {ssh_status}\n"
            f"Публичный RDP: {endpoint_status}\n"
            f"{self.icon('globe')} RDP через Bakunity: {rdp_hermes_connections}\n"
            f"{self.icon('home')} RDP напрямую (LAN/VPN): {rdp_direct_connections}\n"
            f"{rdp_other_line}"
            f"{command_line}\n"
            f"Сессии Windows: {escape(', '.join(sessions) or 'нет')}\n"
            f"Аптайм Windows: {format_duration(telemetry.get('uptime_seconds'))}\n\n"
            f"{self.icon('list')} Процессы\n"
            f"{process_status}\n"
            f"{process_body}\n\n"
            f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        )

        if pending_action:
            control_rows = [
                [self.button("timer", "КОМАНДА ВЫПОЛНЯЕТСЯ", "refresh", style="primary")]
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
                        "ПЕРЕЗАПУСК",
                        f"cmd:restart:{device['id']}",
                        style="primary",
                    )
                ],
            ]
        else:
            control_rows = [[
                self.button(
                    "access_on",
                    "ВКЛЮЧИТЬ ДОСТУП",
                    f"cmd:on:{device['id']}",
                    style="success",
                ),
            ]]

        live_text = (
            f"СТОП · {live_remaining}с"
            if live_active
            else "НАБЛЮДАТЬ 60с"
        )
        keyboard = {
            "inline_keyboard": control_rows + [
                [
                    self.button("refresh", "ОБНОВИТЬ", "refresh", style="primary"),
                    self.button(
                        "watch_off" if live_active else "watch",
                        live_text,
                        "live",
                        style=None if live_active else "primary",
                    ),
                ],
                [
                    self.button(
                        "delete",
                        "УДАЛИТЬ",
                        f"delete:{device['id']}",
                        style="danger",
                    ),
                    self.button("back", "К СПИСКУ", "home"),
                ],
            ]
        }
        return text[:4000], keyboard

    def _delete(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        text = (
            f"{self.icon('warning')} УДАЛЕНИЕ УСТРОЙСТВА\n\n"
            f"Компьютер: {escape(device['display_name'])}\n"
            f"RDP: {self.config.public_host}:{device['rdp_port']}\n\n"
            "API-token и SSH-ключ будут отозваны, а RDP-порт освобождён. "
            "Локальный клиент нужно удалить отдельным скриптом на Windows-ПК."
        )
        keyboard = {
            "inline_keyboard": [
                [
                    self.button(
                        "delete",
                        "УДАЛИТЬ",
                        f"delete_yes:{device['id']}",
                        style="danger",
                    ),
                    self.button(
                        "cancel",
                        "ОТМЕНА",
                        f"device:{device['id']}",
                    ),
                ]
            ]
        }
        return text, keyboard

    def _render_content(self) -> tuple[str, dict[str, Any]]:
        screen = self.registry.get_setting("screen", "home") or "home"
        if screen == "pair":
            return self._pair()
        if screen in {"device", "delete"}:
            device_id = self.registry.get_setting("selected_device", "") or ""
            try:
                device = self.registry.get_device(device_id)
            except KeyError:
                self.registry.set_setting("screen", "home")
                return self._home()
            return self._delete(device) if screen == "delete" else self._device(device)
        return self._home()

    def _remember_device_signature(self) -> None:
        self.last_device_signature = self._device_signature()

    def render(self, force_new: bool = False) -> None:
        with self.lock:
            text, keyboard = self._render_content()
            message_id = self.registry.get_setting("dashboard_message_id", "") or ""
            if force_new and message_id:
                try:
                    self.api_call(
                        "deleteMessage",
                        {
                            "chat_id": self.config.telegram_chat_id,
                            "message_id": int(message_id),
                        },
                        timeout=15,
                    )
                except Exception as exc:
                    LOG.debug("old dashboard delete failed: %s", exc)
                self.registry.set_setting("dashboard_message_id", "")
                message_id = ""
            if message_id and not force_new:
                try:
                    self._render_api_call(
                        "editMessageText",
                        {
                            "chat_id": self.config.telegram_chat_id,
                            "message_id": int(message_id),
                            "text": text,
                            "parse_mode": "HTML",
                            "reply_markup": keyboard,
                        },
                    )
                    self.last_render = time.time()
                    self._remember_device_signature()
                    return
                except Exception as exc:
                    value = str(exc).lower()
                    if "message is not modified" in value:
                        self._remember_device_signature()
                        return
                    if "message to edit not found" not in value and "message can't be edited" not in value:
                        raise
            result = self._render_api_call(
                "sendMessage",
                {
                    "chat_id": self.config.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                },
            )
            self.registry.set_setting("dashboard_message_id", str(result["message_id"]))
            self.last_render = time.time()
            self._remember_device_signature()
