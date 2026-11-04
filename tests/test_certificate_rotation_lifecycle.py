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


class CertificateRotationLifecycleTests(unittest.TestCase):
    def test_fresh_install_stages_same_immutable_cert_lifecycle_before_pairing(self) -> None:
        script = read_ps("scripts/install-client-core.ps1")
        for marker in (
            "Resolve-RepositorySha",
            "$ResolvedSha/client/HermesRdpAgent.ps1",
            "$ResolvedSha/scripts/setup-client-cert-rotation.ps1",
            "Assert-PowerShellFile -Path $AgentCandidate",
            "Assert-PowerShellFile -Path $CertSetupCandidate",
            "Get-NativePowerShellPath",
            "Sysnative",
            "Invoke-CertificateRotationSetup",
            "-ResolvedSha $ResolvedSha",
            "Сертификат RDP: автоматическое управление",
        ):
            self.assertIn(marker, script)

        self.assertLess(
            script.index("Assert-PowerShellFile -Path $CertSetupCandidate"),
            script.index("$PairRequestStarted = $true"),
        )
        self.assertGreater(
            script.rindex("Invoke-CertificateRotationSetup"),
            script.index("$TunnelProcess = Wait-HermesTunnelReady"),
        )
        self.assertLess(
            script.rindex("Invoke-CertificateRotationSetup"),
            script.index("Write-Host '=== ГОТОВО ==='"),
        )

    def test_update_composes_cert_subtransaction_before_final_pass(self) -> None:
        script = read_ps("scripts/update-client.ps1")
        for marker in (
            "$ResolvedSha/client/HermesRdpAgent.ps1",
            "$ResolvedSha/scripts/setup-client-cert-rotation.ps1",
            "Assert-PowerShellFile -Path $CandidatePath",
            "Assert-PowerShellFile -Path $CertSetupCandidate",
            "candidate_cert_setup_sha256",
            "Get-NativePowerShellPath",
            "Sysnative",
            "Certificate rotation setup failed",
            "CertificateRotation: managed",
        ):
            self.assertIn(marker, script)

        self.assertLess(
            script.index("Assert-PowerShellFile -Path $CertSetupCandidate"),
            script.index("$MutationStarted = $false"),
        )
        self.assertGreater(
            script.rindex("Invoke-CertificateRotationSetup"),
            script.index("$Ready = Wait-HermesRuntimeReady"),
        )
        self.assertLess(
            script.rindex("Invoke-CertificateRotationSetup"),
            script.index("Write-Host 'UPDATE=PASS'"),
        )
        self.assertIn("ROLLBACK=PASS", script)

    def test_repair_keeps_accepted_core_and_wraps_cert_lifecycle_transactionally(self) -> None:
        wrapper = read_ps("scripts/repair-client.ps1")
        core_path = ROOT / "scripts/repair-client-core.ps1"
        self.assertTrue(core_path.is_file())

        # The accepted pre-CERT-013 Repair implementation is preserved exactly
        # as the internal core. This prevents lifecycle composition from silently
        # rewriting identity/control/recovery behavior that was already live-tested.
        self.assertEqual(
            git_blob_sha(core_path),
            "4e56efc80ea3b62c5db25ebd9fef89120dd93c05",
        )

        for marker in (
            "$ResolvedSha/scripts/repair-client-core.ps1",
            "$ResolvedSha/scripts/setup-client-cert-rotation.ps1",
            "Assert-PowerShellFile -Path $CoreCandidate",
            "Assert-PowerShellFile -Path $CertSetupCandidate",
            "Get-NativePowerShellPath",
            "Sysnative",
            "Restore-MainSnapshot",
            "CERT-013_REPAIR_ROLLBACK=PASS",
            "CERT-013_REPAIR=PASS",
            "CertificateRotation: managed",
        ):
            self.assertIn(marker, wrapper)

        self.assertLess(
            wrapper.index("Assert-PowerShellFile -Path $CertSetupCandidate"),
            wrapper.index("$TaskBefore = Get-ScheduledTask"),
        )
        self.assertLess(
            wrapper.index("$CoreOutput = & $NativePowerShell"),
            wrapper.index("$CertOutput = & $NativePowerShell"),
        )
        self.assertGreater(
            wrapper.index("Restore-MainSnapshot"),
            wrapper.index("function Restore-MainSnapshot"),
        )

    def test_uninstall_stops_rotation_task_and_worker(self) -> None:
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
