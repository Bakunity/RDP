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
        if self._emoji_packs_loaded:
            return
        self._emoji_packs_loaded = True
        for pack_name in APPROVED_PACKS:
            try:
                sticker_set = self.api_call(
                    "getStickerSet",
                    {"name": pack_name},
                    timeout=15,
                )
                self.emoji.learn_pack(pack_name, sticker_set)
            except Exception as exc:
                LOG.debug("custom emoji pack %s unavailable: %s", pack_name, exc)

    def icon(self, name: str) -> str:
        return self.emoji.html(name)

    def button(
        self,
        icon: str,
        text: str,
        callback_data: str,
        *,
        style: str | None = None,
    ) -> dict[str, Any]:
        return self.emoji.button(
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
            if (
                self.emoji.enabled
                and self.emoji.payload_has_custom_emoji(payload)
                and self._is_custom_emoji_error(exc)
            ):
                LOG.info("custom emoji unavailable; falling back to unicode: %s", exc)
                self.emoji.enabled = False
                text, keyboard = self._render_content()
                fallback_payload = dict(payload)
                fallback_payload["text"] = text
                fallback_payload["reply_markup"] = keyboard
                return self.api_call(method, fallback_payload)
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
                self.render()
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
        if self.registry.get_setting("screen", "home") != "device":
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
                if screen != "device":
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
            "🖥 BAKUNITY RDP · КОМПЬЮТЕРЫ\n\n"
            f"Онлайн: {online} из {len(devices)}\n"
            f"OpenSSH-туннели: порт {self.config.ssh_bind_port}\n"
            f"Диапазон RDP: {self.config.port_start}–{self.config.port_end}\n"
            f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        )
        rows = []
        for device in devices:
            icon = "🟢" if self._online(device) else "🔴"
            rows.append(
                [
                    {
                        "text": f"{icon} {device['display_name']} · :{device['rdp_port']}",
                        "callback_data": f"device:{device['id']}",
                    }
                ]
            )
        rows.append([{"text": "➕ ДОБАВИТЬ ПК", "callback_data": "add"}])
        rows.append([{"text": "🔄 ОБНОВИТЬ", "callback_data": "refresh"}])
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
            "➕ ДОБАВЛЕНИЕ WINDOWS-ПК\n\n"
            f"Код: {code}\n"
            f"Действует: {self.config.pair_ttl_seconds // 60} минут\n\n"
            "1. Открой PowerShell от администратора на новом ПК.\n"
            "2. Вставь команду ниже.\n"
            "3. Установщик спросит удобное название компьютера.\n\n"
            f"<pre><code>{html.escape(command)}</code></pre>"
        )
        keyboard = {"inline_keyboard": [[{"text": "⬅️ К СПИСКУ", "callback_data": "home"}]]}
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
                    f"Наблюдение: 🟢 ещё {live_remaining} сек."
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
                process_status = f"Наблюдение: 🟢 ещё {live_remaining} сек. · ждём первый снимок"

        desired_access = bool(device.get("enabled", True))
        if online and "access_enabled" in telemetry:
            applied_access = "🟢 ВКЛЮЧЕН" if bool(telemetry["access_enabled"]) else "⚪ ВЫКЛЮЧЕН"
        else:
            applied_access = "⚪ НЕИЗВЕСТНО"

        ssh_status = "⚪ НЕИЗВЕСТНО"
        if online and "ssh_tunnel_running" in telemetry and "ssh_process_count" in telemetry:
            try:
                ssh_process_count = int(telemetry.get("ssh_process_count") or 0)
            except (TypeError, ValueError):
                ssh_process_count = -1
            ssh_running = bool(telemetry.get("ssh_tunnel_running"))
            if ssh_process_count > 1:
                ssh_status = f"🟠 ДУБЛИ ({ssh_process_count})"
            elif ssh_running and ssh_process_count == 1:
                ssh_status = "🟢 ПОДКЛЮЧЕН"
            elif not ssh_running and ssh_process_count == 0:
                ssh_status = "⚪ ОТКЛЮЧЕН"
            else:
                ssh_status = "🟠 НЕСООТВЕТСТВИЕ"

        if online and "endpoint_available" in telemetry:
            endpoint_status = "🟢 ОТКРЫТ" if bool(telemetry["endpoint_available"]) else "⚪ ЗАКРЫТ"
        else:
            endpoint_status = "⚪ НЕИЗВЕСТНО"

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
            command_line = "⏳ Команда: " + action_names.get(pending_action, pending_action) + "…"
        elif last_result:
            result_icon = "✅" if last_result.get("ok") else "❌"
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
                client_status = f"✅ АКТУАЛЕН · {client_ref[:7]}"
            elif client_ref and desired_ref:
                client_status = f"⬆️ ОБНОВЛЕНИЕ · {client_ref[:7]} → {desired_ref[:7]}"
            else:
                client_status = "🟠 REF НЕИЗВЕСТЕН"
        else:
            client_status = "⚪ LEGACY · нужен один ручной Repair"

        if (
            bool(getattr(self.config, "trusted_rdp_certificate_enabled", False))
            and online
            and "certificate_lifecycle_ok" in telemetry
        ):
            certificate_status = (
                "✅ MANAGED"
                if bool(telemetry.get("certificate_lifecycle_ok"))
                else "🟠 SELF-HEAL НУЖЕН"
            )
        else:
            certificate_status = "⚪ НЕИЗВЕСТНО"

        maintenance = telemetry.get("maintenance_status") or {}
        maintenance_state = str(maintenance.get("state") or "")
        maintenance_action = str(maintenance.get("action") or "")
        if maintenance_state == "running":
            maintenance_line = f"⏳ {maintenance_action.upper()}"
        elif maintenance_state == "failed":
            maintenance_line = f"❌ {maintenance_action.upper()}"
        elif maintenance_state == "completed" and maintenance.get("ok"):
            maintenance_line = f"✅ {maintenance_action.upper()}"
        else:
            maintenance_line = "—"

        resource_line = (
            f"Ресурсы: {resource_age} сек. назад\n"
            if resource_age is not None
            else "Ресурсы: ещё не поступили\n"
        )
        process_body = "\n".join(process_lines) if process_lines else "—"

        text = (
            f"{'🟢' if online else '🔴'} {escape(device['display_name']).upper()} · "
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
            f"⬇️ Получено: {format_bytes(telemetry.get('network_received_bytes'))}\n"
            f"⬆️ Отправлено: {format_bytes(telemetry.get('network_sent_bytes'))}\n"
            f"Маршрут: {escape(telemetry.get('route', '—'))}\n\n"
            "СОСТОЯНИЕ\n"
            f"Агент: {'🟢 В СЕТИ' if online else '🔴 НЕ В СЕТИ'}\n"
            f"Клиент: {client_status}\n"
            f"Сертификат: {certificate_status}\n"
            f"Maintenance: {maintenance_line}\n"
            f"RDP-доступ (цель): {'🟢 ВКЛЮЧЕН' if desired_access else '⚪ ВЫКЛЮЧЕН'}\n"
            f"Агент применил: {applied_access}\n"
            f"SSH-туннель: {ssh_status}\n"
            f"Публичный RDP: {endpoint_status}\n"
            f"🌐 RDP через Bakunity: {rdp_hermes_connections}\n"
            f"🏠 RDP напрямую (LAN/VPN): {rdp_direct_connections}\n"
            f"{rdp_other_line}"
            f"{command_line}\n"
            f"Сессии Windows: {escape(', '.join(sessions) or 'нет')}\n"
            f"Аптайм Windows: {format_duration(telemetry.get('uptime_seconds'))}\n\n"
            "🔝 Процессы\n"
            f"{process_status}\n"
            f"{process_body}\n\n"
            f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        )

        if pending_action:
            control_rows = [
                [{"text": "⏳ КОМАНДА ВЫПОЛНЯЕТСЯ", "callback_data": "refresh"}]
            ]
        elif desired_access:
            control_rows = [
                [
                    {
                        "text": "🔴 ВЫКЛЮЧИТЬ ДОСТУП",
                        "callback_data": f"cmd:off:{device['id']}",
                    }
                ],
                [
                    {
                        "text": "♻️ ПЕРЕЗАПУСК",
                        "callback_data": f"cmd:restart:{device['id']}",
                    }
                ],
            ]
        else:
            control_rows = [[
                {"text": "🟢 ВКЛЮЧИТЬ ДОСТУП", "callback_data": f"cmd:on:{device['id']}"},
            ]]

        live_text = (
            f"⏸ СТОП · {live_remaining}с"
            if live_active
            else "▶️ НАБЛЮДАТЬ 60с"
        )
        keyboard = {
            "inline_keyboard": control_rows + [
                [
                    {"text": "🔄 ОБНОВИТЬ", "callback_data": "refresh"},
                    {"text": live_text, "callback_data": "live"},
                ],
                [
                    {"text": "🗑 УДАЛИТЬ", "callback_data": f"delete:{device['id']}"},
                    {"text": "⬅️ К СПИСКУ", "callback_data": "home"},
                ],
            ]
        }
        return text[:4000], keyboard

    def _delete(self, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        text = (
            "⚠️ УДАЛЕНИЕ УСТРОЙСТВА\n\n"
            f"Компьютер: {escape(device['display_name'])}\n"
            f"RDP: {self.config.public_host}:{device['rdp_port']}\n\n"
            "API-token и SSH-ключ будут отозваны, а RDP-порт освобождён. "
            "Локальный клиент нужно удалить отдельным скриптом на Windows-ПК."
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ УДАЛИТЬ", "callback_data": f"delete_yes:{device['id']}"},
                    {"text": "❌ ОТМЕНА", "callback_data": f"device:{device['id']}"},
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
