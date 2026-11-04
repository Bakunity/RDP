from __future__ import annotations

import base64
import json
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from hermes_rdp.api import create_api_server
from hermes_rdp.bot import TelegramBot
from hermes_rdp.config import Config
from hermes_rdp.db import Registry, now


ROOT = Path(__file__).resolve().parents[1]


def ed25519_key(seed: int = 41) -> str:
    algorithm = b"ssh-ed25519"
    key = bytes([seed]) * 32
    blob = (
        struct.pack(">I", len(algorithm))
        + algorithm
        + struct.pack(">I", len(key))
        + key
    )
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


class SoakStabilizationTests(unittest.TestCase):
    def test_slow_tls_client_cannot_block_api_accept_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            cert = temp / "api.crt"
            key = temp / "api.key"
            fingerprint = temp / "api.sha256"
            telegram_token = temp / "telegram-token"
            ssh_host_key = temp / "ssh-host-key.pub"

            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            fingerprint.write_text("AA" * 32, encoding="utf-8")
            telegram_token.write_text("test", encoding="utf-8")
            ssh_host_key.write_text("ssh-ed25519 TEST\n", encoding="utf-8")

            config = Config(
                public_host="127.0.0.1",
                api_port=0,
                ssh_bind_port=7000,
                ssh_user="hermes-tunnel",
                port_start=53389,
                port_end=53420,
                data_dir=temp,
                db_path=temp / "state.sqlite3",
                telegram_token_file=telegram_token,
                telegram_chat_id="1",
                tls_cert_file=cert,
                tls_key_file=key,
                tls_fingerprint_file=fingerprint,
                ssh_host_key_file=ssh_host_key,
                client_installer_url="https://example.invalid/install-client.ps1",
                repository_ref="test",
                close_tunnel_helper=temp / "close-tunnel",
            )
            registry = Registry(
                config.db_path,
                config.port_start,
                config.port_end,
                config.command_timeout_seconds,
            )
            server = create_api_server(config, registry)
            server.tls_handshake_timeout_seconds = 0.5
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = int(server.server_address[1])

            slow = socket.create_connection(("127.0.0.1", port), timeout=1)
            try:
                # Leave the first TCP client silent in the TLS handshake. The
                # second client must still be accepted and served immediately.
                time.sleep(0.1)
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(
                    f"https://127.0.0.1:{port}/healthz",
                    context=context,
                    timeout=2,
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["service"], "hermes-rdp")
            finally:
                slow.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_command_timeout_preserves_desired_state_and_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            registry = Registry(
                Path(temp_name) / "state.sqlite3",
                53389,
                53391,
                command_timeout_seconds=60,
            )
            code = registry.create_pair_code()
            device, _ = registry.pair_device(
                code=code,
                display_name="PC",
                machine_name="PC",
                fingerprint="machine",
                ssh_public_key=ed25519_key(),
            )
            device_id = device["id"]
            seq = registry.queue_command(device_id, "off")

            with registry.connect() as conn:
                conn.execute(
                    "UPDATE devices SET pending_created_at=? WHERE id=?",
                    (now() - 120, device_id),
                )

            expired = registry.expire_stale_commands(60, device_id=device_id)
            self.assertEqual(expired, 1)
            after = registry.get_device(device_id)
            self.assertFalse(after["enabled"])
            self.assertIsNone(after["pending_command"])
            self.assertEqual(after["command_seq"], seq)
            self.assertFalse(after["last_result"]["ok"])
            self.assertEqual(after["last_result"]["status"], "timeout")
            self.assertEqual(after["last_result"]["action"], "off")
            self.assertIn("целевое состояние сохранено", after["last_result"]["message"])

            # A timed-out execution slot must not lock the device forever.
            next_seq = registry.queue_command(device_id, "on")
            self.assertGreater(next_seq, seq)
            self.assertTrue(registry.get_device(device_id)["enabled"])

    def test_late_command_result_cannot_overwrite_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            registry = Registry(
                Path(temp_name) / "state.sqlite3",
                53389,
                53391,
                command_timeout_seconds=60,
            )
            code = registry.create_pair_code()
            device, _ = registry.pair_device(
                code=code,
                display_name="PC",
                machine_name="PC",
                fingerprint="machine",
                ssh_public_key=ed25519_key(42),
            )
            device_id = device["id"]
            seq = registry.queue_command(device_id, "off")

            with registry.connect() as conn:
                conn.execute(
                    "UPDATE devices SET pending_created_at=? WHERE id=?",
                    (now() - 120, device_id),
                )

            self.assertEqual(
                registry.expire_stale_commands(60, device_id=device_id),
                1,
            )
            timed_out = registry.get_device(device_id)["last_result"]

            accepted = registry.complete_command(
                device_id,
                seq,
                True,
                "late success",
            )
            self.assertFalse(accepted)
            after_late = registry.get_device(device_id)
            self.assertEqual(after_late["last_result"], timed_out)
            self.assertIsNone(after_late["pending_command"])
            self.assertFalse(after_late["enabled"])

            next_seq = registry.queue_command(device_id, "on")
            self.assertGreater(next_seq, seq)
            self.assertFalse(
                registry.complete_command(device_id, seq, True, "older result")
            )
            pending = registry.get_device(device_id)
            self.assertEqual(pending["command_seq"], next_seq)
            self.assertEqual(pending["pending_command"], "on")

    def test_agent_polls_control_before_attempting_transport_recovery(self) -> None:
        text = (ROOT / "client/HermesRdpAgent.ps1").read_text(encoding="utf-8-sig")
        loop = text[text.index("while ($true)") :]
        post_index = loop.index("$Response = Invoke-ApiPost")
        transport_index = loop.index(
            "if ($State.enabled -and $SshProcesses.Count -eq 0)"
        )
        self.assertLess(post_index, transport_index)
        self.assertIn("desired_enabled", loop)
        self.assertIn("Control poll error:", loop)
        self.assertIn("Transport reconcile error:", loop)

        startup = text[text.index("$Config = Read-JsonFile") : text.index("while ($true)")]
        self.assertNotIn("[void](Start-SshTunnel)", startup)

    def test_command_state_is_persisted_before_transport_action(self) -> None:
        text = (ROOT / "client/HermesRdpAgent.ps1").read_text(encoding="utf-8-sig")
        start = text.index("function Invoke-CommandAction")
        end = text.index("if (-not (Test-Path -LiteralPath $ConfigPath))", start)
        block = text[start:end]
        persist_index = block.index("Write-JsonFile -Path $StatePath -Value $State")
        start_index = block.index("$Message = Start-SshTunnel")
        stop_index = block.index("$Message = Stop-SshTunnel")
        restart_index = block.index("$Message = Restart-SshTunnel")
        self.assertLess(persist_index, start_index)
        self.assertLess(persist_index, stop_index)
        self.assertLess(persist_index, restart_index)

    def test_api_returns_durable_desired_state(self) -> None:
        text = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn('"desired_enabled": bool(current["enabled"])', text)
        self.assertNotIn(
            "server.socket = context.wrap_socket(server.socket, server_side=True)",
            text,
        )
        self.assertIn("process_request_thread", text)
        self.assertIn("tls_handshake_timeout_seconds", text)

    def test_dashboard_actions_are_mobile_friendly(self) -> None:
        bot = TelegramBot.__new__(TelegramBot)
        bot.config = SimpleNamespace(
            public_host="example.test",
            online_after_seconds=15,
        )
        bot.registry = SimpleNamespace(
            get_setting=lambda key, default=None: default,
        )
        timestamp = int(time.time())
        device = {
            "id": "device-1",
            "display_name": "PC",
            "machine_name": "PC",
            "rdp_port": 53389,
            "enabled": True,
            "last_seen": timestamp,
            "pending_command": None,
            "last_result": None,
            "telemetry": {
                "resource_captured_at": timestamp,
                "access_enabled": True,
                "ssh_tunnel_running": True,
                "ssh_process_count": 1,
                "endpoint_available": True,
                "rdp_hermes_connections": 0,
                "rdp_direct_connections": 0,
                "sessions": [],
            },
        }

        _, keyboard = bot._device(device)
        rows = keyboard["inline_keyboard"]

        self.assertEqual(len(rows[0]), 1)
        self.assertEqual(rows[0][0]["text"], "ВЫКЛЮЧИТЬ ДОСТУП")
        self.assertTrue(rows[0][0].get("icon_custom_emoji_id"))
        self.assertEqual(rows[0][0].get("style"), "danger")
        self.assertEqual(len(rows[1]), 1)
        self.assertEqual(rows[1][0]["text"], "ПЕРЕЗАПУСК")
        self.assertTrue(rows[1][0].get("icon_custom_emoji_id"))

    def test_dashboard_signature_tracks_control_state_changes(self) -> None:
        timestamp = int(time.time())
        device = {
            "id": "device-1",
            "enabled": True,
            "last_seen": timestamp,
            "command_seq": 1,
            "pending_command": None,
            "last_result": None,
            "telemetry": {
                "access_enabled": True,
                "ssh_tunnel_running": True,
                "ssh_process_count": 1,
                "endpoint_available": True,
            },
        }

        class RegistryStub:
            def get_setting(self, key, default=None):
                values = {
                    "screen": "device",
                    "selected_device": "device-1",
                }
                return values.get(key, default)

            def get_device(self, device_id):
                self.assert_device(device_id)
                return device

            @staticmethod
            def assert_device(device_id):
                if device_id != "device-1":
                    raise KeyError(device_id)

        bot = TelegramBot.__new__(TelegramBot)
        bot.config = SimpleNamespace(online_after_seconds=15)
        bot.registry = RegistryStub()

        before = bot._device_signature()
        device["pending_command"] = "off"
        device["command_seq"] = 2
        pending = bot._device_signature()
        self.assertNotEqual(before, pending)

        device["pending_command"] = None
        device["enabled"] = False
        device["last_result"] = {
            "seq": 2,
            "action": "off",
            "ok": True,
        }
        device["telemetry"]["access_enabled"] = False
        device["telemetry"]["ssh_tunnel_running"] = False
        device["telemetry"]["ssh_process_count"] = 0
        device["telemetry"]["endpoint_available"] = False
        completed = bot._device_signature()
        self.assertNotEqual(pending, completed)

        source = (ROOT / "server/hermes_rdp/bot.py").read_text(encoding="utf-8")
        self.assertIn("if signature != self.last_device_signature:", source)
        self.assertIn("self._remember_device_signature()", source)


if __name__ == "__main__":
    unittest.main()
