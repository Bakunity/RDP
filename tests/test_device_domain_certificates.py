from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeviceDomainCertificateTests(unittest.TestCase):
    def test_device_helper_derives_hostname_from_authenticated_device_state(self) -> None:
        helper = (
            ROOT / "server/bin/hermes-rdp-device-cert-package.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("SELECT id,slug FROM devices WHERE id=? AND revoked=0", helper)
        self.assertIn("SELECT value FROM settings WHERE key='device_domain'", helper)
        self.assertIn('host = f"{slug}.{domain}"', helper)
        self.assertIn("bakunity-rdp-device-{device_id}", helper)
        self.assertNotIn("--hostname", helper)

    def test_device_helper_uses_http01_and_per_device_rsa_certificate(self) -> None:
        helper = (
            ROOT / "server/bin/hermes-rdp-device-cert-package.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--preferred-challenges http", helper)
        self.assertIn("--renew-with-new-domains", helper)
        self.assertIn('openssl x509 -in "$LIVE/cert.pem" -noout -checkhost "$HOST"', helper)
        self.assertIn("--key-type rsa", helper)
        self.assertIn("--rsa-key-size 2048", helper)
        self.assertIn("server_name *.$DOMAIN;", helper)

    def test_existing_certificate_api_switches_to_device_helper_when_domain_enabled(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn("DEVICE_CERT_PACKAGE_HELPER", api)
        self.assertIn("self.server.registry.get_device_domain()", api)
        self.assertIn('"--status"', api)
        self.assertIn('"--package"', api)
        self.assertIn("CERT_STATE_FILE", api)

    def test_updater_installs_and_rolls_back_device_certificate_helper(self) -> None:
        update = (ROOT / "scripts/update-server.sh").read_text(encoding="utf-8")
        helper = "/usr/local/sbin/hermes-rdp-device-cert-package"
        self.assertIn(helper, update)
        self.assertIn(f"restore_optional_file {helper}", update)
        self.assertIn("server/bin/hermes-rdp-device-cert-package.sh", update)

    def test_certificate_renewal_covers_all_certbot_lineages(self) -> None:
        renew = (
            ROOT / "server/bin/hermes-rdp-cert-renew.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('"$CERTBOT" renew', renew)
        self.assertNotIn('--cert-name "$CERT_NAME"', renew)

    def test_sudo_helper_is_bounded_by_device_id_validation(self) -> None:
        helper = (
            ROOT / "server/bin/hermes-rdp-device-cert-package.sh"
        ).read_text(encoding="utf-8")
        sudoers = (
            ROOT / "server/sudoers/hermes-rdp-cert-package"
        ).read_text(encoding="utf-8")
        self.assertIn("^[0-9a-fA-F]{32}$", helper)
        self.assertIn(
            "/usr/local/sbin/hermes-rdp-device-cert-package *",
            sudoers,
        )


if __name__ == "__main__":
    unittest.main()
