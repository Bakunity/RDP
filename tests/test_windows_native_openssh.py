from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WindowsNativeOpenSshTests(unittest.TestCase):
    def test_x86_powershell_uses_sysnative_probe(self) -> None:
        text = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        for value in (
            "Is64BitOperatingSystem",
            "Is64BitProcess",
            "Sysnative",
            "$CanonicalSystem32",
            "$ProbeSshPath",
        ):
            self.assertIn(value, text)
        self.assertIn("ssh = $SshPath", text)
        self.assertIn("keygen = $KeygenPath", text)

    def test_existing_install_is_detected_before_destructive_actions(self) -> None:
        text = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        guard = text.index("$ExistingConfigPath")
        stop_tasks = text.index("$LegacyTasks = @(")
        stop_processes = text.index("Stop-HermesProcesses", stop_tasks)
        backup = text.index("$BackupDir = Join-Path", stop_processes)
        self.assertLess(guard, stop_tasks)
        self.assertLess(guard, stop_processes)
        self.assertLess(guard, backup)
        self.assertIn("Hermes RDP уже установлен на этом ПК", text)
        self.assertIn("repair/update flow", text)

    def test_installer_supports_client_and_windows_server_product_types(self) -> None:
        text = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$IsClientWindows", text)
        self.assertIn("$IsServerWindows", text)
        self.assertIn("ProductType -in @(2, 3)", text)
        self.assertIn("Windows Server", text)
        self.assertNotIn("$Os.ProductType -ne 1", text)
        self.assertNotIn("Установщик предназначен для клиентской Windows", text)


if __name__ == "__main__":
    unittest.main()
