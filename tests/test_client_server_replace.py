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


class ClientServerReplaceTests(unittest.TestCase):
    def test_accepted_installer_is_preserved_as_core(self) -> None:
        core = ROOT / "scripts/install-client-core.ps1"
        self.assertTrue(core.is_file())
        self.assertEqual(
            git_blob_sha(core),
            "5eef32da26da79e0c56809c45cf7cc13bc7937ed",
        )

    def test_previous_replace_wrapper_is_preserved_unchanged(self) -> None:
        wrapper = ROOT / "scripts/install-client-replace.ps1"
        self.assertTrue(wrapper.is_file())
        self.assertEqual(
            git_blob_sha(wrapper),
            "9c7807943fc46637cf7bcd953d579fab3d2cb750",
        )

    def test_entrypoint_keeps_public_parameter_contract(self) -> None:
        entry = read_ps("scripts/install-client.ps1")
        for marker in (
            "[string]$Server",
            "[string]$PairCode",
            "[string]$Fingerprint",
            "[int]$ApiPort = 7443",
            "[string]$RepositoryRef = 'main'",
            "[switch]$ReplaceExisting",
            "Resolve-RepositorySha",
            "$ResolvedSha/scripts/install-client-replace.ps1",
            "RepositoryRef = $ResolvedSha",
        ):
            self.assertIn(marker, entry)

    def test_incomplete_same_server_self_heals_without_pairing_or_rekey(self) -> None:
        entry = read_ps("scripts/install-client.ps1")
        for marker in (
            "function Test-HermesInstallComplete",
            "$RotationPath = Join-Path $BaseDir 'HermesRdpCertRotation.ps1'",
            "$SyncPath = Join-Path $BaseDir 'sync-rdp-certificate.ps1'",
            "$RotationTaskName = 'Hermes RDP Certificate Rotation'",
            "SSLCertificateSHA1HashType -ne 3",
            "Cert:\\LocalMachine\\My",
            "$ResolvedSha/scripts/repair-client.ps1",
            "-ExpectedDeviceId ([string]$Config.device_id)",
            "без нового pairing и без смены identity",
            "SELF_HEAL=PASS",
        ):
            self.assertIn(marker, entry)

        same_server = entry.index("if ($SameServer)")
        self_heal = entry.index("Invoke-SameServerSelfHeal", same_server)
        delegate = entry.index("& $ReplaceCandidate @Params")
        self.assertLess(same_server, self_heal)
        self.assertLess(self_heal, delegate)

        heal_start = entry.index("function Invoke-SameServerSelfHeal")
        heal_end = entry.index("$ResolvedSha = Resolve-RepositorySha", heal_start)
        heal_body = entry[heal_start:heal_end]
        self.assertNotIn("PairCode", heal_body)
        self.assertNotIn("ssh-keygen", heal_body)
        self.assertNotIn("/v1/pair", heal_body)

    def test_complete_same_server_keeps_guard(self) -> None:
        entry = read_ps("scripts/install-client.ps1")
        self.assertIn("if (Test-HermesInstallComplete)", entry)
        self.assertIn("уже полностью установлен", entry)
        self.assertIn("Repair/Update", entry)
        guard = entry.index("if (Test-HermesInstallComplete)")
        self_heal_call = entry.index("Invoke-SameServerSelfHeal", guard)
        self.assertLess(guard, self_heal_call)

    def test_fresh_and_replace_require_final_invariants(self) -> None:
        entry = read_ps("scripts/install-client.ps1")
        run_delegate = entry.index("& $ReplaceCandidate @Params")
        verify = entry.index("if (-not (Test-HermesInstallComplete))", run_delegate)
        passed = entry.index("INSTALL_INVARIANTS=PASS", verify)
        self.assertLess(run_delegate, verify)
        self.assertLess(verify, passed)

    def test_different_server_requires_explicit_replace_and_new_identity(self) -> None:
        wrapper = read_ps("scripts/install-client-replace.ps1")
        for marker in (
            "=== HERMES RDP SERVER REPLACE ===",
            "Введите REPLACE для переподключения к новому серверу",
            "Move-Item -LiteralPath $BaseDir -Destination $BackupDir",
            "Remove-HermesTask -TaskName $AgentTaskName",
            "Remove-HermesTask -TaskName $RotationTaskName",
            "& $CoreCandidate @CoreParams",
            "REPLACE=PASS",
        ):
            self.assertIn(marker, wrapper)

        move_old = wrapper.index(
            "Move-Item -LiteralPath $BaseDir -Destination $BackupDir"
        )
        run_core = wrapper.index("& $CoreCandidate @CoreParams")
        self.assertLess(move_old, run_core)

    def test_old_registration_is_revoked_only_after_new_core_succeeds(self) -> None:
        wrapper = read_ps("scripts/install-client-replace.ps1")
        run_core = wrapper.index("& $CoreCandidate @CoreParams")
        revoke = wrapper.index(
            "$OldRevoke = Invoke-PinnedRevoke -Config $ExistingConfig"
        )
        self.assertLess(run_core, revoke)
        self.assertIn("HermesRdpReplace.PinnedHttpClientFactory", wrapper)
        self.assertIn("/revoke-self", wrapper)
        self.assertIn("client-replaced-server", wrapper)

    def test_replace_failure_restores_old_files_and_tasks(self) -> None:
        wrapper = read_ps("scripts/install-client-replace.ps1")
        for marker in (
            "Get-TaskSnapshot -TaskName $AgentTaskName",
            "Get-TaskSnapshot -TaskName $RotationTaskName",
            "Restore-TaskSnapshot",
            "Move-Item -LiteralPath $BackupDir -Destination $BaseDir",
            "REPLACE_ROLLBACK=PASS",
        ):
            self.assertIn(marker, wrapper)

        rollback = wrapper.index("REPLACE_ROLLBACK=PASS")
        old_revoke = wrapper.index("$OldRevoke = Invoke-PinnedRevoke")
        self.assertGreater(rollback, old_revoke)

    def test_old_revoke_failure_does_not_break_new_install(self) -> None:
        wrapper = read_ps("scripts/install-client-replace.ps1")
        self.assertIn("Старый сервер недоступен", wrapper)
        self.assertIn("Новый Hermes ", wrapper)
        self.assertIn("уже работает; удали", wrapper)
        self.assertIn("OLD_REGISTRATION=$OldRevoke", wrapper)


if __name__ == "__main__":
    unittest.main()
