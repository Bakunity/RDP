from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutomaticClientMaintenanceTests(unittest.TestCase):
    def test_server_publishes_pinned_client_maintenance_target(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        config = (ROOT / "server/hermes_rdp/config.py").read_text(encoding="utf-8")
        self.assertIn('"desired_client_ref": self.server.config.repository_ref', api)
        self.assertIn('"trusted_rdp_certificate_enabled"', api)
        self.assertIn('command["repository_ref"] = self.server.config.repository_ref', api)
        self.assertIn("trusted_rdp_certificate_enabled: bool = False", config)

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
        install = (ROOT / "scripts/install-client-core.ps1").read_text(encoding="utf-8")
        repair = (ROOT / "scripts/repair-client.ps1").read_text(encoding="utf-8")
        update = (ROOT / "scripts/update-client.ps1").read_text(encoding="utf-8")
        for text in (install, repair, update):
            self.assertIn("client-ref.txt", text)
            self.assertIn("$ResolvedSha", text)
        self.assertIn("Set-SecretAcl -Path $Secret", install)
        self.assertIn("Write-ClientRef -ResolvedSha $ResolvedSha", repair)
        self.assertIn("Write-ClientRef -ResolvedSha $ResolvedSha", update)

    def test_uninstall_cleans_maintenance_task(self) -> None:
        uninstall = (ROOT / "scripts/uninstall-client-core.ps1").read_text(encoding="utf-8")
        self.assertIn("$MaintenanceTaskName = 'Hermes RDP Maintenance'", uninstall)
        self.assertIn("$MaintenanceTaskName))", uninstall)
        self.assertIn("HermesRdpMaintenance.ps1", uninstall)

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
