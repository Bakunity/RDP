from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutomaticClientMaintenanceTests(unittest.TestCase):
    def test_server_publishes_pinned_client_maintenance_target(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        config = (ROOT / "server/hermes_rdp/config.py").read_text(encoding="utf-8")
        self.assertIn('"desired_client_ref": desired_client_ref', api)
        self.assertIn("is_client_ref_compatible(reported_client_ref)", api)
        self.assertIn('"trusted_rdp_certificate_enabled"', api)
        self.assertIn('command["repository_ref"] = self.server.config.client_ref', api)
        self.assertIn("trusted_rdp_certificate_enabled: bool = False", config)
        self.assertIn("client_repository_ref: str = \"\"", config)
        self.assertIn("client_compatible_refs: tuple[str, ...] = ()", config)
        self.assertIn("def client_ref(self) -> str:", config)
        self.assertIn("def is_client_ref_compatible", config)

    def test_telegram_status_is_russian_and_distinguishes_update_failure(self) -> None:
        bot = (ROOT / "server/hermes_rdp/bot.py").read_text(encoding="utf-8")
        self.assertIn("ОЖИДАЕТ ОБНОВЛЕНИЯ", bot)
        self.assertIn("ОБНОВЛЯЕТСЯ", bot)
        self.assertIn("ОШИБКА ОБНОВЛЕНИЯ", bot)
        self.assertIn("Обслуживание:", bot)
        self.assertIn("УПРАВЛЯЕТСЯ", bot)
        self.assertIn("НУЖНО ВОССТАНОВЛЕНИЕ", bot)
        self.assertNotIn('f"Maintenance: {maintenance_line}', bot)
        self.assertNotIn(" MANAGED", bot)
        self.assertNotIn(" SELF-HEAL ", bot)

    def test_telegram_hides_terminal_update_noise_for_current_compatible_client(self) -> None:
        bot = (ROOT / "server/hermes_rdp/bot.py").read_text(encoding="utf-8")
        self.assertIn('maintenance_action == "update"', bot)
        self.assertIn('maintenance_state in {"failed", "completed"}', bot)
        self.assertIn("self._client_ref_is_compatible(client_ref)", bot)
        self.assertIn("maintenance_relevant = False", bot)
        self.assertIn("Keep running updates visible", bot)
        self.assertIn("do not", bot)
        self.assertIn("suppress repair failures", bot)

    def test_live_telemetry_supports_layered_device_screens(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn(
            'in {"device", "device_details", "device_technical"}',
            api,
        )

    def test_registry_maintenance_commands_do_not_redefine_access(self) -> None:
        db = (ROOT / "server/hermes_rdp/db.py").read_text(encoding="utf-8")
        self.assertIn('{"on", "off", "restart", "repair", "update"}', db)
        self.assertIn('else int(row["enabled"])', db)

    def test_agent_auto_update_is_pinned_idle_and_cooldown_bounded(self) -> None:
        agent = (ROOT / "client/HermesRdpAgent.ps1").read_text(encoding="utf-8")
        self.assertIn("desired_client_ref", agent)
        self.assertIn("Automatic update queued", agent)
        self.assertIn("rdp_connections -gt 0", agent)
        self.assertIn("$AutoMaintenanceRetrySeconds = 3600", agent)
        self.assertIn("$CertificateHealthSeconds = 60", agent)
        self.assertIn("Read-CertificateLifecycleHealth", agent)
        self.assertIn("$script:CertificateHealthCapturedAt", agent)
        self.assertIn("maintenance-active.json", agent)
        self.assertIn("Hermes RDP Maintenance", agent)
        self.assertIn("maintenance_capable = $true", agent)
        self.assertIn("certificate_lifecycle_ok", agent)
        self.assertIn(
            "https://raw.githubusercontent.com/bakunity/RDP/$RepositoryRef/client/HermesRdpMaintenance.ps1",
            agent,
        )
        self.assertNotIn(
            "https://raw.githubusercontent.com/bakunity/RDP/main/client/HermesRdpMaintenance.ps1",
            agent,
        )

    def test_maintenance_runner_only_executes_exact_sha_for_same_device(self) -> None:
        runner = (ROOT / "client/HermesRdpMaintenance.ps1").read_text(encoding="utf-8")
        self.assertIn("^[0-9a-fA-F]{40}$", runner)
        self.assertIn("ExpectedDeviceId", runner)
        self.assertIn("[string]$Config.device_id -ne $ExpectedDeviceId", runner)
        self.assertIn("$RepositoryRef/scripts/$ScriptName", runner)
        self.assertIn("maintenance-status.json", runner)
        self.assertIn("maintenance-active.json", runner)

    def test_client_ref_is_persisted_by_install_repair_and_update(self) -> None:
        install = (ROOT / "scripts/install-client.ps1").read_text(encoding="utf-8")
        repair = (ROOT / "scripts/repair-client.ps1").read_text(encoding="utf-8")
        update = (ROOT / "scripts/update-client.ps1").read_text(encoding="utf-8")
        for text in (install, repair, update):
            self.assertIn("client-ref.txt", text)
            self.assertIn("$ResolvedSha", text)
        self.assertIn("Write-ClientRef -ResolvedSha $ResolvedSha", install)
        self.assertIn("Write-ClientRef -ResolvedSha $ResolvedSha", repair)
        self.assertIn("Write-ClientRef -ResolvedSha $ResolvedSha", update)

    def test_uninstall_cleans_maintenance_task(self) -> None:
        uninstall = (ROOT / "scripts/uninstall-client.ps1").read_text(encoding="utf-8")
        self.assertIn("$MaintenanceTaskName = 'Hermes RDP Maintenance'", uninstall)
        self.assertIn("function Remove-MaintenanceTask", uninstall)
        self.assertIn("Unregister-ScheduledTask -TaskName $MaintenanceTaskName", uninstall)

    def test_telegram_product_status_is_simple_and_diagnostics_are_separate(self) -> None:
        ux = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        bot = (ROOT / "server/hermes_rdp/bot.py").read_text(encoding="utf-8")

        home = ux.split("    def _home(", 1)[1].split("    def _human_status(", 1)[0]
        product = ux.split(
            "    def _device(self, device: dict[str, Any])",
            1,
        )[1].split("    def _device_edit(", 1)[0]

        self.assertNotIn("OpenSSH", home)
        self.assertNotIn("Диапазон RDP", home)
        self.assertNotIn("SSH-туннель:", product)
        self.assertNotIn("Клиент:", product)
        self.assertNotIn("Обслуживание:", product)
        self.assertIn("Подключение работает", ux)
        self.assertIn("Удалённый доступ включён", ux)
        self.assertIn("Защищённое подключение настроено", ux)
        self.assertIn("Система работает нормально", ux)
        self.assertIn("ТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ", ux)
        self.assertIn('self.registry.set_setting("screen", "device_technical")', ux)
        self.assertIn('"device_technical"', bot)

    def test_telegram_has_one_click_repair_and_legacy_fallback(self) -> None:
        ux = (ROOT / "server/hermes_rdp/bot_ux.py").read_text(encoding="utf-8")
        bot = (ROOT / "server/hermes_rdp/bot.py").read_text(encoding="utf-8")
        self.assertIn('self.registry.queue_command(device_id, "repair")', ux)
        self.assertIn("maintenance_capable", ux)
        self.assertIn("один ручной Repair", ux)
        self.assertIn('"repair": "восстановление клиента"', bot)
        self.assertIn("Клиент: {client_status}", bot)
        self.assertIn("Сертификат: {certificate_status}", bot)


if __name__ == "__main__":
    unittest.main()
