from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsCertificatePinningTests(unittest.TestCase):
    def test_installer_uses_static_csharp_validator(self) -> None:
        text = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("class PinnedHttpClientFactory", text)
        self.assertIn("ValidateCertificate", text)
        self.assertIn("ServerCertificateCustomValidationCallback = delegate", text)
        self.assertIn("[HermesRdp.PinnedHttpClientFactory]::Create", text)
        self.assertNotIn("$Handler.ServerCertificateCustomValidationCallback = {", text)
        self.assertNotIn("param($Request, $Certificate, $Chain, $SslPolicyErrors)", text)

    def test_windows_runtime_test_exists(self) -> None:
        text = (ROOT / "tests/Test-PinnedHttpClient.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("static-csharp-cert-pinning=PASS", text)
        self.assertIn("Correct certificate fingerprint was rejected", text)
        self.assertIn("Incorrect certificate fingerprint was accepted", text)


if __name__ == "__main__":
    unittest.main()
