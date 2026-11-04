from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_rdp.cli import build_parser
from hermes_rdp.db import Registry, hash_secret


ROOT = Path(__file__).resolve().parents[1]


class NamedAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "state.sqlite3"
        self.registry = Registry(self.db_path, 53389, 53420)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_connector_tokens_are_hashed_independent_and_revocable(self) -> None:
        first, first_token = self.registry.create_named_access_token("Main PC")
        second, second_token = self.registry.create_named_access_token("Laptop")

        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first_token, second_token)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT token_hash FROM named_access_tokens WHERE id=?",
                (first["id"],),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], hash_secret(first_token))
        self.assertNotEqual(row[0], first_token)

        authenticated = self.registry.authenticate_named_access_token(first_token)
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated["id"], first["id"])
        self.assertIsInstance(authenticated["last_seen"], int)

        self.registry.revoke_named_access_token(first["id"])
        self.assertIsNone(
            self.registry.authenticate_named_access_token(first_token)
        )
        self.assertEqual(
            self.registry.authenticate_named_access_token(second_token)["id"],
            second["id"],
        )

    def test_cli_exposes_named_access_connector_lifecycle(self) -> None:
        parser = build_parser()

        created = parser.parse_args(
            ["named-access", "create", "--name", "Main PC"]
        )
        self.assertEqual(created.command, "named-access")
        self.assertEqual(created.named_access_command, "create")
        self.assertEqual(created.name, "Main PC")

        listed = parser.parse_args(["named-access", "list"])
        self.assertEqual(listed.named_access_command, "list")

        revoked = parser.parse_args(
            ["named-access", "revoke", "abc123"]
        )
        self.assertEqual(revoked.named_access_command, "revoke")
        self.assertEqual(revoked.connector_id, "abc123")

        routed = parser.parse_args(
            ["named-access", "route", "abc123", "p2p"]
        )
        self.assertEqual(routed.named_access_command, "route")
        self.assertEqual(routed.connector_id, "abc123")
        self.assertEqual(routed.policy, "p2p")

    def test_connector_smart_route_policy_and_telemetry_persist(self) -> None:
        connector, token = self.registry.create_named_access_token("Laptop")
        self.assertEqual(connector["route_policy"], "auto")

        self.registry.set_named_access_route_policy(
            connector["id"],
            "p2p",
        )
        self.registry.update_named_access_telemetry(
            connector["id"],
            machine_name="LAPTOP-01",
            telemetry={
                "mesh": {
                    "installed": True,
                    "online": True,
                    "ipv4": "192.0.2.10",
                },
                "routes": {
                    "dev123": {
                        "route": "p2p",
                        "latency_ms": 18,
                    }
                },
            },
        )

        authenticated = self.registry.authenticate_named_access_token(token)
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated["route_policy"], "p2p")
        self.assertEqual(authenticated["machine_name"], "LAPTOP-01")
        self.assertTrue(authenticated["telemetry"]["mesh"]["online"])

        with self.assertRaisesRegex(ValueError, "route policy"):
            self.registry.set_named_access_route_policy(
                connector["id"],
                "fastest",
            )

    def test_manifest_is_get_only_and_contains_no_connector_secret(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        self.assertIn('path == "/v1/named-access/manifest"', api)
        self.assertIn("authenticate_named_access_token", api)
        self.assertIn('"hostname": f"{slug}.{domain}"', api)
        self.assertIn('"rdp_port": int(device["rdp_port"])', api)
        self.assertIn('"manifest_version": 2', api)
        self.assertIn('"routes": {', api)
        self.assertIn('"p2p": {', api)
        self.assertIn('"relay": {', api)
        self.assertIn('path == "/v1/named-access/telemetry"', api)
        self.assertNotIn('"token_hash"', api)
        self.assertNotIn('"access_token"', api)

    def test_windows_worker_is_pinned_bounded_and_incremental(self) -> None:
        worker = (
            ROOT / "client/BakunityNamedAccess.ps1"
        ).read_text(encoding="utf-8-sig")

        for marker in (
            "BakunityRdpNamedAccess.PinnedHttpClientFactory",
            "/v1/named-access/manifest",
            "AuthenticationHeaderValue",
            "127.77.",
            "interface portproxy add v4tov4",
            "$ListenPort = 3389",
            "connectport=$RemotePort",
            "# BEGIN BAKUNITY RDP NAMED ACCESS",
            "# END BAKUNITY RDP NAMED ACCESS",
            "Local TCP 3389 is already owned by another listener",
            "Test-MappingSetChanged",
            "SYNC=UNCHANGED",
            "Get-NativeSystem32",
        ):
            self.assertIn(marker, worker)

        self.assertNotIn("portproxy reset", worker)
        self.assertNotIn("Set-Service", worker)
        self.assertNotIn("Disable-NetFirewallRule", worker)

    def test_installer_uses_system_task_immutable_ref_and_secret_acl(self) -> None:
        installer = (
            ROOT / "scripts/install-named-access.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Resolve-RepositorySha",
            "Bakunity RDP Named Access",
            "New-ScheduledTaskPrincipal -UserId 'SYSTEM'",
            "Set-SystemAdminAcl -Path $ConfigPath",
            "BakunityNamedAccess.ps1",
            "NAMED_ACCESS_INSTALL=PASS",
            "Cleanup-FreshNamedAccessRuntime",
        ):
            self.assertIn(marker, installer)

    def test_named_access_acl_separates_secret_config_from_readable_state(self) -> None:
        installer = (
            ROOT / "scripts/install-named-access.ps1"
        ).read_text(encoding="utf-8-sig")
        worker = (
            ROOT / "client/BakunityNamedAccess.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn(
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)",
            installer,
        )
        self.assertIn(
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)",
            worker,
        )
        self.assertNotIn("O:SYG:SYD:P", installer)
        self.assertNotIn("O:SYG:SYD:P", worker)

    def test_installer_auto_falls_back_to_launcher_when_local_3389_is_owned(self) -> None:
        installer = (
            ROOT / "scripts/install-named-access.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Get-NamedAccessRoutingMode",
            "Get-NetTCPConnection",
            "return 'launcher'",
            "return 'portproxy'",
            "routing_mode = $RoutingMode",
            "Install-LauncherShortcut",
            "Bakunity RDP.lnk",
            "ROUTING_MODE=$RoutingMode",
        ):
            self.assertIn(marker, installer)

    def test_launcher_accepts_hostname_without_port_and_invokes_mstsc(self) -> None:
        launcher = (
            ROOT / "client/BakunityRdpLaunch.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "[string]$Computer",
            "Do not include an RDP port",
            "Bakunity device not found",
            "CONNECTING=$($Target.hostname)",
            'Start-Process -FilePath $Mstsc -ArgumentList @("/v:$Endpoint")',
            "Microsoft.VisualBasic.Interaction",
        ):
            self.assertIn(marker, launcher)

    def test_worker_launcher_mode_never_requires_local_3389(self) -> None:
        worker = (
            ROOT / "client/BakunityNamedAccess.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("$RoutingMode -eq 'launcher'", worker)
        self.assertIn("SYNC=PASS mode=launcher", worker)
        self.assertIn("Remove-PortProxyRuntime", worker)
        launcher_branch = worker.split(
            "if ($RoutingMode -eq 'launcher')",
            1,
        )[1].split("Start-IpHelper", 1)[0]
        self.assertNotIn("Assert-LocalRdpPortAvailable", launcher_branch)

    def test_smart_route_worker_selects_lan_p2p_then_relay(self) -> None:
        worker = (
            ROOT / "client/BakunitySmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Select-DeviceRoute",
            "@('auto','lan')",
            "@('auto','p2p')",
            "@('auto','relay')",
            "Test-TcpCandidate",
            "route_type",
            "latency_ms",
            "/v1/named-access/telemetry",
            "manifest_version -ne 2",
        ):
            self.assertIn(marker, worker)

    def test_smart_route_installer_is_one_command_system_task(self) -> None:
        installer = (
            ROOT / "scripts/install-smart-route-connector.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Resolve-RepositorySha",
            "Bakunity RDP Smart Route",
            "New-ScheduledTaskPrincipal -UserId 'SYSTEM'",
            "BakunitySmartRoute.ps1",
            "BakunitySmartRouteLaunch.ps1",
            "SMART_ROUTE_INSTALL=PASS",
        ):
            self.assertIn(marker, installer)

    def test_smart_route_launcher_uses_local_proxy_endpoint(self) -> None:
        launcher = (
            ROOT / "client/BakunitySmartRouteLaunch.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("local_port", launcher)
        self.assertIn("ROUTE=", launcher)
        self.assertIn('Start-Process -FilePath $Mstsc', launcher)

    def test_uninstall_removes_only_recorded_named_access_runtime(self) -> None:
        uninstall = (
            ROOT / "scripts/uninstall-named-access.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("$State.mappings.PSObject.Properties", uninstall)
        self.assertIn("127\\.77", uninstall)
        self.assertIn("portproxy delete v4tov4", uninstall)
        self.assertIn("Remove-ManagedHostsBlock", uninstall)
        self.assertIn("Bakunity RDP.lnk", uninstall)
        self.assertNotIn("portproxy reset", uninstall)
        self.assertNotIn("Hermes RDP Agent", uninstall)


if __name__ == "__main__":
    unittest.main()
