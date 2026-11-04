from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_rdp.api import parse_helper_json as parse_api_helper_json
from hermes_rdp.cli import parse_helper_json as parse_cli_helper_json
from hermes_rdp.device_certificates import (
    get_device_certificate_target,
    set_device_slug_with_certificate,
)
from hermes_rdp.db import normalize_device_slug


ROOT = Path(__file__).resolve().parents[1]




class FakeCertificateRegistry:
    def __init__(self) -> None:
        self.slug = "old"
        self.settings: dict[str, str] = {}

    def get_device_domain(self) -> str:
        return "tima.biz"

    def get_device(self, device_id: str) -> dict:
        if device_id != "dev123":
            raise KeyError(device_id)
        return {"id": device_id, "slug": self.slug}

    def set_device_slug(self, device_id: str, slug: str) -> str:
        if device_id != "dev123":
            raise KeyError(device_id)
        clean = str(slug).strip().lower()
        if not clean:
            raise ValueError("invalid device slug")
        self.slug = clean
        return clean

    def get_setting(self, key: str, default: str = "") -> str:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


class DeviceDomainCertificateTests(unittest.TestCase):
    def test_slug_change_publishes_new_certificate_target(self) -> None:
        registry = FakeCertificateRegistry()
        config = SimpleNamespace(trusted_rdp_certificate_enabled=True)
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "cert_name": "tima.tima.biz",
                    "thumbprint": "A" * 40,
                    "sha256": "B" * 64,
                    "not_after": "2030-01-01",
                }
            ),
            stderr="",
        )
        with patch(
            "hermes_rdp.device_certificates.subprocess.run",
            return_value=completed,
        ):
            slug, target = set_device_slug_with_certificate(
                config,
                registry,
                "dev123",
                "tima",
            )

        self.assertEqual(slug, "tima")
        self.assertEqual(registry.slug, "tima")
        self.assertEqual(target["cert_name"], "tima.tima.biz")
        self.assertEqual(target["thumbprint"], "A" * 40)
        self.assertEqual(
            get_device_certificate_target(registry, "dev123"),
            target,
        )

    def test_slug_change_rolls_back_when_certificate_issuance_fails(self) -> None:
        registry = FakeCertificateRegistry()
        config = SimpleNamespace(trusted_rdp_certificate_enabled=True)
        completed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="ACME failed",
        )
        with patch(
            "hermes_rdp.device_certificates.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(RuntimeError, "ACME failed"):
                set_device_slug_with_certificate(
                    config,
                    registry,
                    "dev123",
                    "broken",
                )

        self.assertEqual(registry.slug, "old")
        self.assertIsNone(
            get_device_certificate_target(registry, "dev123")
        )

    def test_agent_reconciles_certificate_target_without_waiting_for_rotation(self) -> None:
        agent = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn("desired_rdp_certificate_thumbprint", api)
        self.assertIn("desired_rdp_certificate_name", api)
        self.assertIn("Invoke-CertificateTargetReconcile", agent)
        self.assertIn("rdp_certificate_thumbprint", agent)
        self.assertIn("$CertificateTargetRetrySeconds = 60", agent)
        self.assertIn("$CertificateSyncPath", agent)
        self.assertIn("rdp_connections -gt 0", agent)

    def test_certificate_sync_is_serialized(self) -> None:
        sync = (
            ROOT / "scripts/sync-rdp-certificate.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("Global\\HermesRdpCertificateSync", sync)
        self.assertIn("$SyncMutex.WaitOne", sync)
        self.assertIn("$SyncMutex.ReleaseMutex()", sync)

    def test_numeric_device_slugs_are_valid(self) -> None:
        self.assertEqual(normalize_device_slug("2"), "2")
        self.assertEqual(normalize_device_slug("PC-2026"), "pc-2026")

    def test_controller_sandbox_allows_only_certificate_write_roots(self) -> None:
        service = (
            ROOT / "server/systemd/hermes-rdp.service"
        ).read_text(encoding="utf-8")
        self.assertIn("ProtectSystem=strict", service)
        for path in (
            "/etc/letsencrypt",
            "/var/lib/letsencrypt",
            "/var/log/letsencrypt",
            "/var/www/hermes-rdp-acme",
            "/etc/nginx/conf.d",
            "/etc/nginx/sites-enabled",
        ):
            self.assertIn(f"ReadWritePaths=-{path}", service)

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

    def test_certbot_output_cannot_pollute_machine_json_channel(self) -> None:
        helper = (
            ROOT / "server/bin/hermes-rdp-device-cert-package.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--quiet", helper)
        self.assertIn("1>&2", helper)
        self.assertIn("stdout is a machine-readable channel", helper)

    def test_cli_and_api_accept_trailing_json_after_tool_noise(self) -> None:
        text = (
            "Saving debug log to /var/log/letsencrypt/letsencrypt.log\n"
            "Certificate not yet due for renewal\n"
            '{"cert_name":"mipc.tima.biz","thumbprint":"ABC"}\n'
        )
        self.assertEqual(
            parse_cli_helper_json(text)["cert_name"],
            "mipc.tima.biz",
        )
        self.assertEqual(
            parse_api_helper_json(text)["thumbprint"],
            "ABC",
        )

    def test_cli_and_api_reject_output_without_json_object(self) -> None:
        for parser in (parse_cli_helper_json, parse_api_helper_json):
            with self.assertRaises(ValueError):
                parser("certbot output only\n")

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
