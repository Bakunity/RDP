from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsRdpCertificateRotationTests(unittest.TestCase):
    def test_api_authenticates_before_root_package_helper(self) -> None:
        text = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn('action == "rdp-certificate"', text)
        method = text[text.index("    def _rdp_certificate"):]
        self.assertLess(method.index("self._device_auth(device_id)"), method.index("subprocess.run("))
        self.assertIn('["sudo", "-n", CERT_PACKAGE_HELPER]', method)
        self.assertIn("HTTPStatus.UNAUTHORIZED", method)
        self.assertIn("HTTPStatus.SERVICE_UNAVAILABLE", method)
        self.assertNotIn("privkey.pem", text)

    def test_root_helper_is_bounded_to_current_trusted_lineage(self) -> None:
        text = (ROOT / "server/bin/hermes-rdp-cert-package.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            "set -Eeuo pipefail",
            "umask 077",
            "trusted_rdp_certificate",
            "openssl x509 -in \"$CERT\" -noout -checkip \"$CERT_NAME\"",
            "openssl pkcs12 -export",
            "openssl rand -hex 24",
            "mktemp -d",
            "base64 -w 0",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("$1", text)
        self.assertNotIn("eval ", text)

        sudoers = (ROOT / "server/sudoers/hermes-rdp-cert-package").read_text(
            encoding="utf-8"
        ).strip().splitlines()
        self.assertIn(
            "hermes-rdp ALL=(root) NOPASSWD: /usr/local/sbin/hermes-rdp-cert-package",
            sudoers,
        )
        self.assertIn(
            "hermes-rdp ALL=(root) NOPASSWD: /usr/local/sbin/hermes-rdp-device-cert-package *",
            sudoers,
        )

    def test_windows_sync_uses_pinned_authenticated_nonexportable_flow(self) -> None:
        text = (ROOT / "scripts/sync-rdp-certificate.ps1").read_text(
            encoding="utf-8-sig"
        )
        for marker in (
            "CertificatePinnedHttpClientFactory",
            "api_fingerprint",
            "AuthenticationHeaderValue",
            "device_token",
            "/rdp-certificate",
            "Import-PfxCertificate",
            "Cert:\\LocalMachine\\My",
            "S-1-5-20",
            "SSLCertificateSHA1Hash",
            "rdp-certificate-backup.json",
            "AUTO_ROLLBACK=PASS",
            "PRIVATE_KEY_EXPORTABLE=False",
            "HASH_TYPE=CUSTOM",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("-Exportable", text)
        self.assertEqual(text.count("=== CERT-011 ==="), 1)

    def test_windows_sync_restores_default_and_custom_bindings_differently(self) -> None:
        text = (ROOT / "scripts/sync-rdp-certificate.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("function Restore-RdpBinding", text)
        self.assertIn("if ($HashType -eq 1)", text)
        self.assertIn("Remove-ItemProperty", text)
        self.assertIn("-Name SSLCertificateSHA1Hash", text)
        self.assertIn("SSLCertificateSHA1HashType -ne 1", text)
        self.assertIn("if ($HashType -eq 3)", text)
        self.assertIn("Set-RdpThumbprint -Thumbprint $Clean", text)
        self.assertIn("previous_hash_type = $PreviousHashType", text)
        self.assertIn("Restore-RdpBinding `", text)
        self.assertNotIn("Restore-FunctionalBinding", text)

    def test_setup_updater_and_uninstall_manage_helper_transactionally(self) -> None:
        setup = (ROOT / "scripts/setup-trusted-rdp-cert.sh").read_text(
            encoding="utf-8"
        )
        updater = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        uninstall = (ROOT / "scripts/uninstall-server.sh").read_text(encoding="utf-8")

        for marker in (
            "hermes-rdp-cert-package.sh",
            "hermes-rdp-device-cert-package.sh",
            "/usr/local/sbin/hermes-rdp-cert-package",
            "/usr/local/sbin/hermes-rdp-device-cert-package",
            "/etc/sudoers.d/hermes-rdp-cert-package",
            "visudo -cf /etc/sudoers.d/hermes-rdp-cert-package",
        ):
            self.assertIn(marker, setup)
            self.assertIn(marker, updater)

        self.assertIn("TRUSTED_CERT_ENABLED", updater)
        self.assertIn("restore_optional_file /usr/local/sbin/hermes-rdp-cert-package", updater)
        self.assertIn("restore_optional_file /usr/local/sbin/hermes-rdp-device-cert-package", updater)
        self.assertIn("restore_optional_file /etc/sudoers.d/hermes-rdp-cert-package", updater)
        self.assertIn("/usr/local/sbin/hermes-rdp-cert-package", uninstall)
        self.assertIn("/usr/local/sbin/hermes-rdp-device-cert-package", uninstall)
        self.assertIn("/etc/sudoers.d/hermes-rdp-cert-package", uninstall)


if __name__ == "__main__":
    unittest.main()
