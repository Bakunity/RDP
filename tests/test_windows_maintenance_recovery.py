from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsMaintenanceRecoveryTests(unittest.TestCase):
    def test_agent_requires_real_process_not_task_state_alone(self) -> None:
        text = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Get-ScheduledTask -TaskName $MaintenanceTaskName",
            "function Get-MaintenanceProcesses",
            "Get-CimInstance",
            "Win32_Process",
            '$Line.Contains($MaintenanceRunnerPath)',
            "$Line.Contains('HermesRdpMaintenance.ps1')",
            "Stop-GhostMaintenanceTask",
            "Stopped ghost maintenance scheduled task with no live PowerShell process",
        ):
            self.assertIn(marker, text)

    def test_agent_recovers_stale_lock_and_marks_running_status_failed(self) -> None:
        text = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Recovered stale maintenance lock:",
            "Stale maintenance lock recovered automatically",
            "$Status.state = 'failed'",
            "$Status.ok = $false",
            "Remove-Item -LiteralPath $MaintenanceActivePath",
        ):
            self.assertIn(marker, text)

    def test_start_task_recovers_ghost_scheduler_state(self) -> None:
        text = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            "$LiveMaintenance = @(Get-MaintenanceProcesses)",
            text,
        )
        self.assertIn(
            "Stop-GhostMaintenanceTask -Task $ExistingTask",
            text,
        )
        self.assertIn(
            "return 'maintenance task already running'",
            text,
        )

    def test_agent_no_longer_trusts_lock_age_alone(self) -> None:
        text = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertNotIn(
            "$StartedAt -gt 0 -and $Age -lt 3600",
            text,
        )


if __name__ == "__main__":
    unittest.main()
