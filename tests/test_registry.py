import base64
import struct
import tempfile
import unittest
from pathlib import Path

from hermes_rdp.db import Registry, normalize_ssh_public_key


def ed25519_key(seed: int = 1) -> str:
    algorithm = b"ssh-ed25519"
    key = bytes([seed]) * 32
    blob = (
        struct.pack(">I", len(algorithm))
        + algorithm
        + struct.pack(">I", len(key))
        + key
    )
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = Registry(
            Path(self.temp.name) / "state.sqlite3",
            53389,
            53391,
        )

    def tearDown(self):
        self.temp.cleanup()

    def pair(self, *, name="PC", key=None, port=None):
        code = self.registry.create_pair_code(
            display_name=name,
            preferred_port=port,
        )
        return self.registry.pair_device(
            code=code,
            display_name=name,
            machine_name=name,
            fingerprint="machine",
            ssh_public_key=key or ed25519_key(),
        )

    def test_pair_register_authenticate_and_authorize_ssh(self):
        device, token = self.pair(
            name="Windows-PC-01",
            port=53389,
        )
        self.assertEqual(device["display_name"], "Windows-PC-01")
        self.assertEqual(device["rdp_port"], 53389)
        self.assertIsNotNone(
            self.registry.authenticate(device["id"], token)
        )
        self.assertIsNone(
            self.registry.authenticate(device["id"], "wrong")
        )
        key_type, key_blob = device["ssh_public_key"].split()
        authorized = self.registry.authorize_ssh_key(
            key_type,
            key_blob,
        )
        self.assertEqual(authorized["id"], device["id"])

    def test_auto_port_allocation(self):
        for offset, expected in enumerate((53389, 53390, 53391), 1):
            device, _ = self.pair(
                name=f"PC {expected}",
                key=ed25519_key(offset),
            )
            self.assertEqual(device["rdp_port"], expected)
        with self.assertRaises(RuntimeError):
            self.registry.allocate_port()

    def test_pair_is_atomic_when_key_is_duplicate(self):
        self.pair(key=ed25519_key(1))
        code = self.registry.create_pair_code()
        with self.assertRaises(ValueError):
            self.registry.pair_device(
                code=code,
                display_name="Duplicate",
                machine_name="DUPLICATE",
                fingerprint="x",
                ssh_public_key=ed25519_key(1),
            )
        device, _ = self.registry.pair_device(
            code=code,
            display_name="Recovered",
            machine_name="RECOVERED",
            fingerprint="x",
            ssh_public_key=ed25519_key(2),
        )
        self.assertEqual(device["rdp_port"], 53390)

    def test_disabled_and_revoked_keys_are_denied(self):
        device, _ = self.pair()
        key_type, key_blob = device["ssh_public_key"].split()
        self.registry.set_enabled(device["id"], False)
        self.assertIsNone(
            self.registry.authorize_ssh_key(key_type, key_blob)
        )
        self.registry.set_enabled(device["id"], True)
        self.assertIsNotNone(
            self.registry.authorize_ssh_key(key_type, key_blob)
        )
        self.registry.revoke_device(device["id"])
        self.assertIsNone(
            self.registry.authorize_ssh_key(key_type, key_blob)
        )

    def test_deleted_device_frees_its_rdp_port(self):
        first, _ = self.pair(key=ed25519_key(1), port=53389)
        self.registry.revoke_device(first["id"])
        second, _ = self.pair(key=ed25519_key(2), port=53389)
        self.assertEqual(second["rdp_port"], 53389)

    def test_invalid_key_rejected_without_consuming_code(self):
        code = self.registry.create_pair_code()
        with self.assertRaises(ValueError):
            self.registry.pair_device(
                code=code,
                display_name="Bad",
                machine_name="BAD",
                fingerprint="x",
                ssh_public_key="ssh-rsa AAAA",
            )
        device, _ = self.registry.pair_device(
            code=code,
            display_name="Good",
            machine_name="GOOD",
            fingerprint="x",
            ssh_public_key=ed25519_key(),
        )
        self.assertEqual(device["rdp_port"], 53389)

    def test_key_normalization_removes_comment(self):
        key = ed25519_key()
        self.assertEqual(
            normalize_ssh_public_key(key + " comment"),
            key,
        )

    def test_command_lifecycle(self):
        device, _ = self.pair()
        seq = self.registry.queue_command(device["id"], "restart")
        command = self.registry.update_telemetry(
            device["id"],
            {"cpu_percent": 1},
        )
        self.assertEqual(command["seq"], seq)
        self.assertEqual(command["action"], "restart")
        self.registry.complete_command(device["id"], seq, True, "ok")
        self.assertIsNone(
            self.registry.pending_command(device["id"])
        )

    def test_command_queue_changes_desired_state_atomically(self):
        device, _ = self.pair()
        device_id = device["id"]

        off_seq = self.registry.queue_command(device_id, "off")
        after_off = self.registry.get_device(device_id)
        self.assertFalse(after_off["enabled"])
        self.assertEqual(after_off["pending_command"], "off")
        self.assertEqual(after_off["command_seq"], off_seq)

        with self.assertRaises(ValueError):
            self.registry.queue_command(device_id, "on")
        still_off = self.registry.get_device(device_id)
        self.assertFalse(still_off["enabled"])
        self.assertEqual(still_off["pending_command"], "off")
        self.assertEqual(still_off["command_seq"], off_seq)

        self.registry.complete_command(device_id, off_seq, True, "off applied")
        on_seq = self.registry.queue_command(device_id, "on")
        after_on = self.registry.get_device(device_id)
        self.assertTrue(after_on["enabled"])
        self.assertEqual(after_on["pending_command"], "on")
        self.assertEqual(after_on["command_seq"], on_seq)

    def test_maintenance_commands_preserve_desired_access(self):
        device, _ = self.pair()
        device_id = device["id"]
        self.registry.set_enabled(device_id, False)

        repair_seq = self.registry.queue_command(device_id, "repair")
        after_repair = self.registry.get_device(device_id)
        self.assertFalse(after_repair["enabled"])
        self.assertEqual(after_repair["pending_command"], "repair")
        self.registry.complete_command(device_id, repair_seq, True, "queued")

        update_seq = self.registry.queue_command(device_id, "update")
        after_update = self.registry.get_device(device_id)
        self.assertFalse(after_update["enabled"])
        self.assertEqual(after_update["pending_command"], "update")
        self.assertEqual(after_update["command_seq"], update_seq)


if __name__ == "__main__":
    unittest.main()
