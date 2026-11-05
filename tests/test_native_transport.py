from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_rdp.db import Registry, hash_secret
from hermes_rdp.native_transport import (
    native_transport_windows_artifact,
    normalize_native_transport_host,
)


ROOT = Path(__file__).resolve().parents[1]


class NativeTransportTests(unittest.TestCase):
    def test_native_host_state_requires_valid_peer_for_online(self) -> None:
        valid_peer = "12D3KooWQp6vU5hBq9kL8mN7rS4tV2xY6zA3cD5eF7gH9jK"
        state = normalize_native_transport_host(
            {
                "captured_at": 123,
                "installed": True,
                "online": True,
                "peer_id": valid_peer,
                "relay_connected": True,
                "path": "direct",
                "version": "0.1.0",
            }
        )
        self.assertTrue(state["online"])
        self.assertEqual(state["peer_id"], valid_peer)
        self.assertEqual(state["path"], "direct")

        invalid = normalize_native_transport_host(
            {
                "online": True,
                "peer_id": "not-a-peer-id",
                "path": "something-else",
            }
        )
        self.assertFalse(invalid["peer_id"])
        self.assertEqual(invalid["path"], "idle")

    def test_route_policy_is_scoped_to_connector_and_target_pc(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry = Registry(Path(temp) / "state.sqlite3", 53389, 53420)
            connector, _ = registry.create_named_access_token("Laptop")
            now = 1
            with sqlite3.connect(registry.db_path) as conn:
                for index, device_id in enumerate(("dev-a", "dev-b")):
                    conn.execute(
                        "INSERT INTO devices("
                        "id,display_name,machine_name,fingerprint,token_hash,"
                        "rdp_port,created_at,updated_at,slug"
                        ") VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            device_id,
                            device_id,
                            device_id,
                            "fp",
                            hash_secret("token-" + device_id),
                            53389 + index,
                            now,
                            now,
                            device_id,
                        ),
                    )

            self.assertEqual(
                registry.get_connector_device_route_policy(
                    connector["id"],
                    "dev-a",
                ),
                "auto",
            )
            registry.set_connector_device_route_policy(
                connector["id"],
                "dev-a",
                "p2p",
            )
            self.assertEqual(
                registry.get_connector_device_route_policy(
                    connector["id"],
                    "dev-a",
                ),
                "p2p",
            )
            self.assertEqual(
                registry.get_connector_device_route_policy(
                    connector["id"],
                    "dev-b",
                ),
                "auto",
            )

    def test_go_transport_is_own_rdp_data_plane(self) -> None:
        source = (
            ROOT / "native-transport/cmd/bakunity-transport/main.go"
        ).read_text(encoding="utf-8")
        for marker in (
            '"/bakunity/rdp/1.0.0"',
            "EnableHolePunching",
            "NATPortMap",
            "circuitrelay.WithACL",
            "AllowReserve",
            "AllowConnect",
            "shared secret is too short",
            "invalid transport authorization",
            "127.0.0.1:3389",
            "direct Bakunity path unavailable",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("tailscale", source.lower())
        self.assertNotIn("headscale", source.lower())

    def test_native_relay_setup_is_bounded_and_self_hosted(self) -> None:
        setup = (
            ROOT / "scripts/setup-native-transport.sh"
        ).read_text(encoding="utf-8")
        service = (
            ROOT / "server/systemd/bakunity-transport.service"
        ).read_text(encoding="utf-8")
        for marker in (
            "BAKUNITY_GO_VERSION",
            "sha256sum -c",
            "bakunity-transport.service",
            "ufw allow 7444/tcp",
            "ufw allow 7444/udp",
            '("native_transport_enabled", "1")',
            "BAKUNITY_TRANSPORT=PASS",
        ):
            self.assertIn(marker, setup)
        for marker in (
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ReadWritePaths=/var/lib/bakunity-transport",
            "127.0.0.1:7445",
        ):
            self.assertIn(marker, service)

    def test_vps_native_build_avoids_tmpfs_and_preserves_release_source(self) -> None:
        setup = (
            ROOT / "scripts/setup-native-transport.sh"
        ).read_text(encoding="utf-8")
        for marker in (
            'BUILD_ROOT="${BAKUNITY_TRANSPORT_BUILD_ROOT:-/var/cache/bakunity-transport}"',
            'WORK="$(mktemp -d -p "$BUILD_ROOT" build.XXXXXXXX)"',
            'export TMPDIR="$WORK/tmp"',
            'export GOTMPDIR="$WORK/tmp"',
            'export GOMODCACHE="$WORK/gomod"',
            'export GOCACHE="$WORK/gocache"',
            'export GOFLAGS="-p=1"',
            'cp -a "$ROOT/native-transport"/. "$WORK/module/"',
            "BUILD_DISK_NOT_READY:",
            "BUILD_INODES_NOT_READY:",
        ):
            self.assertIn(marker, setup)
        self.assertNotIn('cd "$ROOT/native-transport"\n', setup)
        self.assertNotIn('WORK="$(mktemp -d)"', setup)

    def test_windows_native_transport_uses_prebuilt_verified_artifact(self) -> None:
        lib = (
            ROOT / "client/BakunityNativeTransport.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "RepositoryRef must be an immutable 40-character SHA",
            "Bakunity Transport artifact checksum mismatch",
            "BakunityNativeTransportDownload.PinnedHttpClientFactory",
            "ResponseHeadersRead",
            "New-ScheduledTaskPrincipal -UserId 'SYSTEM'",
            "Bakunity Transport TCP",
            "Bakunity Transport UDP",
            "Text.UTF8Encoding($false)",
            "Set-BakunityNativeForward",
        ):
            self.assertIn(marker, lib)
        self.assertNotIn("go.dev/dl", lib)
        self.assertNotIn("codeload.github.com", lib)
        self.assertNotIn("Expand-Archive", lib)

    def test_server_builds_and_verifies_windows_transport_artifact(self) -> None:
        builder = (
            ROOT / "scripts/build-native-transport-windows.sh"
        ).read_text(encoding="utf-8")
        for marker in (
            "GOOS=windows GOARCH=amd64",
            "CGO_ENABLED=0",
            "BakunityTransport.exe.sha256",
            "WINDOWS_ARTIFACT_SHA256",
            '[[ "$(head -c 2 "$CANDIDATE")" != "MZ" ]]',
        ):
            self.assertIn(marker, builder)

        setup = (
            ROOT / "scripts/setup-native-transport.sh"
        ).read_text(encoding="utf-8")
        update = (
            ROOT / "scripts/update-server.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("build-native-transport-windows.sh", setup)
        self.assertIn("build-native-transport-windows.sh", update)
        self.assertIn('BAKUNITY_TRANSPORT_CLIENT_REF="$NEW_CLIENT_REF"', update)

    def test_windows_transport_artifact_metadata_is_integrity_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ref = "a" * 40
            root = Path(temp)
            directory = root / ref / "windows-amd64"
            directory.mkdir(parents=True)
            binary = directory / "BakunityTransport.exe"
            binary.write_bytes(b"MZ" + b"bakunity-transport")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            (directory / "BakunityTransport.exe.sha256").write_text(
                digest + "\n",
                encoding="ascii",
            )
            artifact = native_transport_windows_artifact(ref, root=root)
            self.assertEqual(artifact["repository_ref"], ref)
            self.assertEqual(artifact["sha256"], digest)
            self.assertEqual(artifact["size"], binary.stat().st_size)

            binary.write_bytes(b"MZtampered")
            self.assertEqual(
                native_transport_windows_artifact(ref, root=root),
                {},
            )

    def test_native_host_errors_are_reported_without_breaking_fallbacks(self) -> None:
        state_module = (
            ROOT / "server/hermes_rdp/native_transport.py"
        ).read_text(encoding="utf-8")
        host_worker = (
            ROOT / "client/BakunityHostSmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            '"last_error": str(payload.get("last_error") or "")[:500]',
            state_module,
        )
        for marker in (
            "$Telemetry.last_error = $ErrorText",
            "NATIVE_TRANSPORT=ERROR",
            "return $Telemetry",
            "native-transport-telemetry",
        ):
            self.assertIn(marker, host_worker)

    def test_host_native_failure_is_logged_before_best_effort_telemetry(self) -> None:
        host = (
            ROOT / "client/BakunityHostSmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")

        error_log = 'Write-HostRouteLog "NATIVE_TRANSPORT=ERROR $ErrorText"'
        report = '[void](Invoke-PinnedPost -Config $Config -Path "/v1/devices/$DeviceId/native-transport-telemetry"'
        self.assertIn(error_log, host)
        self.assertIn("NATIVE_TELEMETRY=DEFERRED", host)
        self.assertIn("SMART_ROUTE_TELEMETRY=DEFERRED", host)
        self.assertLess(host.index(error_log), host.index(report, host.index(error_log)))
        self.assertIn("return $Telemetry", host)
        self.assertIn("SYNC=PASS", host)

    def test_host_and_connector_both_receive_native_transport_library(self) -> None:
        host_setup = (
            ROOT / "scripts/setup-smart-route-host.ps1"
        ).read_text(encoding="utf-8-sig")
        connector_setup = (
            ROOT / "scripts/install-smart-route-connector.ps1"
        ).read_text(encoding="utf-8-sig")
        host_worker = (
            ROOT / "client/BakunityHostSmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")
        connector_worker = (
            ROOT / "client/BakunitySmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("BakunityNativeTransport.ps1", host_setup)
        self.assertIn("BakunityNativeTransport.ps1", connector_setup)
        self.assertIn("Sync-HostNativeTransport", host_worker)
        self.assertIn("Sync-ConnectorNativeTransport", connector_worker)
        self.assertIn("routes.native", connector_worker)
        self.assertIn("Set-BakunityNativeForward", connector_worker)
        self.assertIn("windows_amd64", host_worker)
        self.assertIn("windows_amd64", connector_worker)
        self.assertIn("-BearerToken ([string]$Config.device_token)", host_worker)
        self.assertIn("-BearerToken ([string]$Config.access_token)", connector_worker)

    def test_native_route_is_preferred_before_legacy_mesh_and_vps_relay(self) -> None:
        worker = (
            ROOT / "client/BakunitySmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")
        native_index = worker.index("$Native = $Device.routes.native")
        legacy_index = worker.index("$P2p = $Device.routes.p2p")
        relay_index = worker.index("$Relay = $Device.routes.relay")
        self.assertLess(native_index, legacy_index)
        self.assertLess(legacy_index, relay_index)
        self.assertIn("'native_p2p'", worker)
        self.assertIn("'native_relay'", worker)

    def test_api_exposes_native_transport_without_replacing_old_relay(self) -> None:
        api = (
            ROOT / "server/hermes_rdp/api.py"
        ).read_text(encoding="utf-8")
        for marker in (
            'path == "/v1/named-access/native-transport-bootstrap"',
            '"/v1/named-access/native-transport/windows-amd64"',
            '["native-transport", "windows-amd64"]',
            'action == "native-transport-telemetry"',
            'action == "native-transport-bootstrap"',
            '"windows_amd64": artifact',
            '"native_transport": {',
            '"relay": {',
        ):
            self.assertIn(marker, api)

    def test_telegram_ux_is_computer_first_and_pair_specific(self) -> None:
        bot = (
            ROOT / "server/hermes_rdp/bot_ux.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "ДОБАВИТЬ КОМПЬЮТЕР",
            "ПРЯМОЕ ПОДКЛЮЧЕНИЕ",
            '"ПОДКЛЮЧЕНИЕ"',
            "device_connection_source",
            "route_pair:",
            "connection_source:{connector['id']}",
            "get_connector_device_route_policy",
            "set_connector_device_route_policy",
            "BAKUNITY P2P",
            "BAKUNITY RELAY",
        ):
            self.assertIn(marker, bot)
        self.assertNotIn('"ДОБАВИТЬ HOST"', bot)
        self.assertNotIn(
            "connection_source:{device['id']}:{connector['id']}",
            bot,
        )
        self.assertNotIn("route_device:", bot)

    def test_update_server_versions_native_transport_source(self) -> None:
        update = (
            ROOT / "scripts/update-server.sh"
        ).read_text(encoding="utf-8")
        for marker in (
            '"client/BakunityNativeTransport.ps1"',
            '"native-transport/go.mod"',
            '"native-transport/cmd/bakunity-transport/main.go"',
            'test -f "$ROOT/scripts/setup-native-transport.sh"',
        ):
            self.assertIn(marker, update)


if __name__ == "__main__":
    unittest.main()
