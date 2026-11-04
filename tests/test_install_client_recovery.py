from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallClientRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )

    def test_startup_uses_bounded_stable_readiness_poll(self) -> None:
        text = self.text
        self.assertIn("$StartupTimeoutSeconds = 75", text)
        self.assertIn("$StartupStableSeconds = 20", text)
        self.assertIn("function Wait-HermesTunnelReady", text)
        self.assertIn("$StablePid", text)
        self.assertIn("Get-HermesSshProcess -KeyPath $KeyPath", text)
        self.assertNotIn("Start-Sleep -Seconds 8", text)

        task_start = text.index("Start-ScheduledTask -TaskName $TaskName")
        readiness = text.index("$TunnelProcess = Wait-HermesTunnelReady", task_start)
        success = text.index("=== ГОТОВО ===", readiness)
        self.assertLess(task_start, readiness)
        self.assertLess(readiness, success)

    def test_failed_install_restores_local_snapshot_after_safe_revoke(self) -> None:
        text = self.text
        self.assertIn("function Restore-InstallSnapshot", text)
        self.assertIn("$PairRequestStarted = $false", text)
        self.assertIn("$PairRequestStarted = $true", text)
        self.assertIn("$ServerRegistrationCleared = -not $PairRequestStarted", text)
        self.assertIn("$ServerRegistrationCleared = $true", text)
        self.assertIn("if ($ServerRegistrationCleared)", text)
        self.assertIn("Restore-InstallSnapshot", text)

        revoke = text.index("/revoke-self")
        cleared = text.index("$ServerRegistrationCleared = $true", revoke)
        restore = text.index("Restore-InstallSnapshot", cleared)
        self.assertLess(revoke, cleared)
        self.assertLess(cleared, restore)

    def test_uncertain_pair_result_preserves_credentials(self) -> None:
        text = self.text
        self.assertIn("elseif ($PairRequestStarted -and -not $Pair)", text)
        self.assertIn("Локальные credentials сохранены", text)
        self.assertIn("проверь устройство в Telegram", text)

    def test_clean_machine_rollback_removes_fresh_base_directory(self) -> None:
        text = self.text
        function_start = text.index("function Restore-InstallSnapshot")
        function_end = text.index("function Ensure-OpenSshClient", function_start)
        function_text = text[function_start:function_end]
        self.assertIn("if (-not $BaseExistedBefore)", function_text)
        self.assertIn("Remove-Item", function_text)
        self.assertIn("-Recurse", function_text)


if __name__ == "__main__":
    unittest.main()
