from __future__ import annotations

import base64
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from hermes_rdp.cli import build_parser
from hermes_rdp.db import (
    Registry,
    normalize_device_domain,
    normalize_device_slug,
)


def ed25519_key(seed: int) -> str:
    algorithm = b"ssh-ed25519"
    key = bytes([seed]) * 32
    blob = (
        struct.pack(">I", len(algorithm))
        + algorithm
        + struct.pack(">I", len(key))
        + key
    )
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


class DeviceDomainSlugTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "state.sqlite3"
        self.registry = Registry(self.db_path, 53389, 53420)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def pair(
        self,
        *,
        seed: int,
        name: str,
        machine_name: str,
        slug: str | None = None,
    ) -> dict:
        code = self.registry.create_pair_code(
            display_name=name,
            slug=slug,
        )
        device, _ = self.registry.pair_device(
            code=code,
            display_name=name,
            machine_name=machine_name,
            fingerprint=f"fp-{seed}",
            ssh_public_key=ed25519_key(seed),
        )
        return device

    def test_slug_normalization_supports_names_and_cyrillic(self) -> None:
        self.assertEqual(normalize_device_slug("Tima PC"), "tima-pc")
        self.assertEqual(normalize_device_slug("Домашний ПК"), "domashniy-pk")
        self.assertEqual(normalize_device_slug(" AI__PC "), "ai-pc")

    def test_domain_normalization_is_strict(self) -> None:
        self.assertEqual(normalize_device_domain("TIMA.BIZ."), "tima.biz")
        with self.assertRaises(ValueError):
            normalize_device_domain("localhost")
        with self.assertRaises(ValueError):
            normalize_device_domain("-bad.tima.biz")

    def test_auto_slugs_are_unique_and_stable_on_rename(self) -> None:
        first = self.pair(seed=1, name="AI", machine_name="AI")
        second = self.pair(seed=2, name="AI", machine_name="AI-2")
        self.assertEqual(first["slug"], "ai")
        self.assertEqual(second["slug"], "ai-2")

        self.registry.rename_device(first["id"], "New Friendly Name")
        after = self.registry.get_device(first["id"])
        self.assertEqual(after["slug"], "ai")

    def test_requested_slug_and_manual_slug_update(self) -> None:
        device = self.pair(
            seed=3,
            name="Workstation",
            machine_name="WORKSTATION",
            slug="tima",
        )
        self.assertEqual(device["slug"], "tima")

        updated = self.registry.set_device_slug(device["id"], "office")
        self.assertEqual(updated, "office")
        self.assertEqual(self.registry.get_device(device["id"])["slug"], "office")

    def test_duplicate_requested_slug_is_rejected(self) -> None:
        self.pair(seed=4, name="One", machine_name="ONE", slug="same")
        with self.assertRaises(ValueError):
            self.registry.create_pair_code(display_name="Two", slug="same")

    def test_device_domain_is_persisted_in_registry_settings(self) -> None:
        self.assertEqual(self.registry.get_device_domain(), "")
        self.assertEqual(self.registry.set_device_domain("tima.biz"), "tima.biz")
        self.assertEqual(self.registry.get_device_domain(), "tima.biz")

        reopened = Registry(self.db_path, 53389, 53420)
        self.assertEqual(reopened.get_device_domain(), "tima.biz")

        reopened.clear_device_domain()
        self.assertEqual(reopened.get_device_domain(), "")

    def test_existing_devices_without_slug_are_backfilled(self) -> None:
        device = self.pair(seed=5, name="Legacy PC", machine_name="LEGACY")
        with self.registry.connect() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_devices_active_slug")
            conn.execute(
                "UPDATE devices SET slug=NULL WHERE id=?",
                (device["id"],),
            )

        upgraded = Registry(self.db_path, 53389, 53420)
        self.assertEqual(upgraded.get_device(device["id"])["slug"], "legacy-pc")

    def test_cli_exposes_domain_and_slug_commands(self) -> None:
        parser = build_parser()

        domain = parser.parse_args(["domain", "set", "tima.biz"])
        self.assertEqual(domain.command, "domain")
        self.assertEqual(domain.domain_command, "set")
        self.assertEqual(domain.domain, "tima.biz")

        slug = parser.parse_args(["devices", "slug", "abc", "tima"])
        self.assertEqual(slug.devices_command, "slug")
        self.assertEqual(slug.device_id, "abc")
        self.assertEqual(slug.slug, "tima")

        pair = parser.parse_args(
            ["pair", "create", "--name", "AI", "--slug", "ai"]
        )
        self.assertEqual(pair.slug, "ai")


if __name__ == "__main__":
    unittest.main()
