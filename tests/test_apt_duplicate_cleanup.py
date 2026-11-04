from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AptDuplicateCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bootstrap = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")

    def test_bootstrap_normalizes_overlapping_simple_deb_lines(self) -> None:
        self.assertIn("normalize_simple_apt_entries_in_file", self.bootstrap)
        self.assertIn("repair_duplicate_apt_warnings", self.bootstrap)
        self.assertIn("is configured multiple times", self.bootstrap)
        self.assertIn("key=part[1] SUBSEP part[2] SUBSEP part[3]", self.bootstrap)
        self.assertIn("component_seen", self.bootstrap)
        self.assertIn("components[key]", self.bootstrap)
        self.assertIn("cmp -s", self.bootstrap)
        self.assertIn("apt-sources-dedupe-", self.bootstrap)
        self.assertIn("source-файлы восстановлены", self.bootstrap)
        self.assertIn("! grep -q 'is configured multiple times'", self.bootstrap)
        self.assertIn('normalize_simple_apt_entries_in_file "$file" || true', self.bootstrap)
        self.assertNotIn("dedupe_exact_entries_in_file", self.bootstrap)

    def test_reported_subset_superset_fixture_merges_components(self) -> None:
        match = re.search(
            r"(normalize_simple_apt_entries_in_file\(\) \{.*?\n\})\n\nrepair_duplicate_apt_warnings\(\)",
            self.bootstrap,
            flags=re.S,
        )
        self.assertIsNotNone(match)
        function = match.group(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sources.list"
            path.write_text(
                "deb https://deb.debian.org/debian/ trixie main contrib\n"
                "\n"
                "# provider image entry\n"
                "deb https://deb.debian.org/debian/ trixie main contrib non-free non-free-firmware\n"
                "deb-src https://deb.debian.org/debian/ trixie main contrib non-free non-free-firmware\n"
                "deb https://deb.debian.org/debian/ trixie-updates main contrib\n",
                encoding="utf-8",
            )
            command = (
                "set -Eeuo pipefail; "
                f"WORK_DIR={tmpdir!r}; "
                f"{function}; "
                f"normalize_simple_apt_entries_in_file {str(path)!r} || true"
            )
            subprocess.run(["bash", "-c", command], check=True)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "deb https://deb.debian.org/debian/ trixie main contrib non-free non-free-firmware\n"
                "\n"
                "# provider image entry\n"
                "deb-src https://deb.debian.org/debian/ trixie main contrib non-free non-free-firmware\n"
                "deb https://deb.debian.org/debian/ trixie-updates main contrib\n",
            )


if __name__ == "__main__":
    unittest.main()
