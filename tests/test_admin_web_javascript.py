from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminWebJavascriptTests(unittest.TestCase):
    def test_embedded_admin_javascript_parses(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")

        source = (ROOT / "server/hermes_rdp/admin_web.py").read_text(
            encoding="utf-8"
        )
        start = source.index("<script>") + len("<script>")
        end = source.index("</script>", start)
        javascript = source[start:end]

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".js",
            delete=False,
        ) as handle:
            handle.write(javascript)
            path = Path(handle.name)

        try:
            completed = subprocess.run(
                [node, "--check", str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr or completed.stdout,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_device_workspace_has_no_legacy_drawer_or_glyph_icons(self) -> None:
        source = (ROOT / "server/hermes_rdp/admin_web.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="page-device"', source)
        self.assertIn('class="icon"', source)
        self.assertNotIn('id="drawerBack"', source)
        for glyph in ("⌂", "▣", "＋", "◫", "↻", "✕", "☰"):
            self.assertNotIn(glyph, source)


if __name__ == "__main__":
    unittest.main()
