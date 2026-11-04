from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_ps(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


class ClientUninstallCompleteTests(unittest.TestCase):
    def test_cert_setup_preserves_first_pre_hermes_binding(self) -> None:
        setup = read_ps("scripts/setup-client-cert-rotation.ps1")
        for marker in (
            "$OriginPath = Join-Path $BaseDir 'rdp-certificate-origin.json'",
            "$LegacyBackupPath = Join-Path $BaseDir 'rdp-certificate-backup.json'",
            "function Initialize-RdpOriginSnapshot",
            "original_thumbprint",
            "original_hash_type",
            "Source = 'CURRENT_LISTENER'",
            "Source = 'LEGACY_BACKUP'",
            "return 'PRESERVED'",
            "$OriginState = Initialize-RdpOriginSnapshot",
            'Write-Host "RDP_ORIGIN=$OriginState"',
        ):
            self.assertIn(marker, setup)

        init = setup.index("$OriginState = Initialize-RdpOriginSnapshot")
        first_sync = setup.index("-File $WorkerPath", init)
        self.assertLess(init, first_sync)

    def test_live_accepted_uninstall_is_preserved_as_core(self) -> None:
        core = ROOT / "scripts/uninstall-client-core.ps1"
        self.assertTrue(core.is_file())
        self.assertEqual(
            git_blob_sha(core),
            "6e379df38e5ab7327aebc892d52d504395078e78",
        )

    def test_core_restores_listener_before_revoking_device(self) -> None:
        script = read_ps("scripts/uninstall-client-core.ps1")
        for marker in (
            "function Get-RdpOriginSnapshot",
            "function Restore-RdpBinding",
            "PASS_$($RollbackSnapshot.Source)",
            "HermesRdpUninstall.PinnedHttpClientFactory",
            "/revoke-self",
            "client-uninstall",
            "LOCAL_STATE=REMOVED",
            "RDP_3389=LISTEN",
            "UNINSTALL=PASS",
        ):
            self.assertIn(marker, script)

        restore = script.index("$RestoredThumbprint = Restore-RdpBinding")
        revoke = script.index("$ServerRevoke = Invoke-PinnedRevoke")
        delete_state = script.index("if (Test-Path -LiteralPath $BaseDir) {", revoke)
        self.assertLess(restore, revoke)
        self.assertLess(revoke, delete_state)

    def test_core_removes_active_state_instead_of_secret_archive(self) -> None:
        script = read_ps("scripts/uninstall-client-core.ps1")
        self.assertNotIn(".removed.", script)
        self.assertIn("LOCAL_TASKS=ABSENT", script)
        self.assertIn("HERMES_PROCESSES=0", script)

    def test_wrapper_normalizes_ambiguous_server_revoke(self) -> None:
        script = read_ps("scripts/uninstall-client.ps1")
        for marker in (
            "$ResolvedSha/scripts/uninstall-client-core.ps1",
            "Invoke-RevokeVerification",
            "client-uninstall-verify",
            "REVOKED_CONFIRMED",
            "UNCONFIRMED_HTTP_",
            "UNCONFIRMED",
            "$CoreOutput = @(& $CoreCandidate -Force *>&1)",
            "SERVER_REVOKE=$ServerRevoke",
        ):
            self.assertIn(marker, script)

        run_core = script.index("$CoreOutput = @(& $CoreCandidate -Force *>&1)")
        verify = script.index("Invoke-RevokeVerification -Config $ConfigBefore", run_core)
        self.assertLess(run_core, verify)

    def test_wrapper_treats_only_confirmed_revoke_as_success(self) -> None:
        script = read_ps("scripts/uninstall-client.ps1")
        self.assertIn("@('REVOKED', 'REVOKED_CONFIRMED')", script)
        self.assertIn("Серверный отзыв устройства не удалось подтвердить", script)

    def test_core_retains_cert013_task_and_worker_cleanup_markers(self) -> None:
        script = read_ps("scripts/uninstall-client-core.ps1")
        for marker in (
            "$RotationTaskName = 'Hermes RDP Certificate Rotation'",
            "$RotationPath = Join-Path $BaseDir 'HermesRdpCertRotation.ps1'",
            "@($TaskName, $RotationTaskName)",
            "Stop-ScheduledTask",
            "Unregister-ScheduledTask",
            "$_.CommandLine.Contains($RotationPath)",
        ):
            self.assertIn(marker, script)


if __name__ == "__main__":
    unittest.main()
