from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nginx_acme_uses_direct_alias_mapping() -> None:
    setup = (ROOT / "scripts/setup-trusted-rdp-cert.sh").read_text(encoding="utf-8")

    assert "ACME_WEBROOT=/var/www/hermes-rdp-acme" in setup
    assert "location ^~ /.well-known/acme-challenge/" in setup
    assert "alias $ACME_WEBROOT/.well-known/acme-challenge/;" in setup
    assert "try_files \\$uri =404;" not in setup
    assert 'curl -fsS --max-time 5 -H "Host: $HOST"' in setup
    assert "nginx ACME webroot probe failed." in setup
