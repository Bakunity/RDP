from pathlib import Path
import unittest


class BakunityCommandAliasTests(unittest.TestCase):
    def test_package_exposes_both_names(self):
        content = Path("server/pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('bakunity-rdpctl = "hermes_rdp.cli:main"', content)
        self.assertIn('hermes-rdpctl = "hermes_rdp.cli:main"', content)

    def test_installer_creates_both_cli_wrappers(self):
        content = Path("scripts/install-server.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/bakunity-rdpctl", content)
        self.assertIn("/usr/local/bin/hermes-rdpctl", content)
        self.assertIn('BAKUNITY_RDP_REF:-${HERMES_RDP_REF:-main}', content)

    def test_public_cli_has_new_name(self):
        content = Path("server/hermes_rdp/cli.py").read_text(encoding="utf-8")
        self.assertIn('prog="bakunity-rdpctl"', content)


if __name__ == "__main__":
    unittest.main()
