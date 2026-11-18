from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from hermes_rdp.auth import (
    create_session,
    generate_password,
    read_credentials,
    verify_password,
    verify_session,
    write_credentials,
)


ROOT = Path(__file__).resolve().parents[1]


class WebAdminAuthTests(unittest.TestCase):
    def test_password_is_hashed_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials.json"
            password = "VeryStrongPassword-2026!"
            write_credentials(
                path,
                username="admin",
                password=password,
            )
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn(password, raw)
            self.assertTrue(
                verify_password(
                    path,
                    username="admin",
                    password=password,
                )
            )
            self.assertFalse(
                verify_password(
                    path,
                    username="admin",
                    password="wrong-password",
                )
            )

    def test_password_reset_invalidates_older_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials.json"
            write_credentials(
                path,
                username="admin",
                password="InitialPassword-2026!",
            )
            first = read_credentials(path)
            self.assertIsNotNone(first)
            token = create_session(
                "signing-secret",
                username="admin",
                ttl_seconds=3600,
            )
            self.assertIsNotNone(
                verify_session(
                    "signing-secret",
                    token,
                    min_issued_at=first.updated_at,
                )
            )
            time.sleep(1)
            write_credentials(
                path,
                username="admin",
                password="ReplacementPassword-2026!",
            )
            second = read_credentials(path)
            self.assertIsNotNone(second)
            self.assertGreater(second.updated_at, first.updated_at)
            self.assertIsNone(
                verify_session(
                    "signing-secret",
                    token,
                    min_issued_at=second.updated_at,
                )
            )

    def test_generated_password_is_nontrivial(self) -> None:
        password = generate_password()
        self.assertGreaterEqual(len(password), 16)
        self.assertTrue(any(ch.isalpha() for ch in password))
        self.assertTrue(any(ch.isdigit() for ch in password))

    def test_api_uses_secure_http_only_session_cookie(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            "__Host-bakunity_admin_session",
            "HttpOnly; Secure; SameSite=Strict",
            "X-Bakunity-Session",
            '"session": token',
            'if path == "/v1/admin/auth/login":',
            'if path == "/v1/admin/auth/logout":',
            'if path == "/v1/admin/auth/status":',
            "verify_password(",
            "create_session(",
            "verify_session(",
            "min_issued_at=credentials.updated_at",
        ):
            self.assertIn(marker, api)

    def test_web_ui_has_no_user_facing_token_login(self) -> None:
        web = (ROOT / "server/hermes_rdp/admin_web.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            'id="loginUser"',
            'id="loginPassword"',
            "/v1/admin/auth/login",
            "/v1/admin/auth/logout",
            "/v1/admin/auth/status",
            "credentials:'same-origin'",
            "bakunity_admin_session",
            "X-Bakunity-Session",
        ):
            self.assertIn(marker, web)
        self.assertNotIn('id="loginToken"', web)
        self.assertNotIn("Web Admin Token", web)
        self.assertNotIn(
            "localStorage.getItem('bakunity_admin_token')",
            web,
        )
        self.assertIn(
            "localStorage.removeItem('bakunity_admin_token')",
            web,
        )
        self.assertIn(
            "localStorage.getItem('bakunity_admin_session')",
            web,
        )
        self.assertIn(
            "localStorage.setItem('bakunity_admin_session',SESSION)",
            web,
        )
        self.assertIn(
            "localStorage.removeItem('bakunity_admin_session')",
            web,
        )

    def test_cli_supports_password_setup_without_shell_history_secret(self) -> None:
        cli = (ROOT / "server/hermes_rdp/cli.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            'sub.add_parser("admin"',
            "admin_password = admin_sub.add_parser(",
            '"password",',
            '"--generate"',
            'getpass.getpass("Новый пароль Web Admin: ")',
            "write_credentials(",
            "ADMIN_AUTH=PASS",
            "PASSWORD=",
        ):
            self.assertIn(marker, cli)

    def test_server_lifecycle_preserves_credentials(self) -> None:
        install = (ROOT / "scripts/install-server.sh").read_text(
            encoding="utf-8"
        )
        update = (ROOT / "scripts/update-server.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"web_admin_credentials_file": '
            '"/etc/hermes-rdp/web-admin-credentials.json"',
            install,
        )
        self.assertNotIn("web_admin_token=$(cat", install)
        self.assertIn(
            "web_admin_password_setup=bakunity-rdpctl admin password --generate",
            install,
        )
        self.assertIn(
            "restore_optional_file "
            "/etc/hermes-rdp/web-admin-credentials.json",
            update,
        )


if __name__ == "__main__":
    unittest.main()
