from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NginxAcmeWebrootAccessTests(unittest.TestCase):
    def test_nginx_webroot_is_outside_private_hermes_state(self) -> None:
        setup = (ROOT / "scripts/setup-trusted-rdp-cert.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("ACME_WEBROOT=/var/www/hermes-rdp-acme", setup)
        self.assertNotIn("ACME_WEBROOT=/var/lib/hermes-rdp/acme-webroot", setup)
        self.assertIn('install -d -m 0755 "$ACME_WEBROOT/.well-known/acme-challenge"', setup)
        self.assertIn('server_name $HOST;', setup)
        self.assertIn('alias $ACME_WEBROOT/.well-known/acme-challenge/;', setup)
        self.assertNotIn('try_files \\$uri =404;', setup)
        self.assertIn('curl -fsS --max-time 2 -H "Host: $HOST"', setup)
        self.assertIn('for attempt in {1..20}', setup)


if __name__ == "__main__":
    unittest.main()
