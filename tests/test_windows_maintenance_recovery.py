from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsMaintenanceRecoveryTests(unittest.TestCase):
    def test_agent_checks_real_task_and_process_before_honoring_lock(self) -> None:
        text = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Get-ScheduledTask -TaskName $MaintenanceTaskName",
            "[string]$Task.State -eq 'Running'",
            "Get-CimInstance Win32_Process",
            '$CommandLine.Contains($MaintenanceRunnerPath)',
            "$CommandLine.Contains('HermesRdpMaintenance')",
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
