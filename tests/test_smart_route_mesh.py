from __future__ import annotations

import ipaddress
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_rdp.smart_route import (
    create_mesh_bootstrap,
    normalize_host_smart_route,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeRegistry:
    def __init__(self) -> None:
        self.settings = {
            "smart_route_enabled": "1",
            "smart_route_control_url": "https://mesh.example.test",
        }

    def get_setting(self, key: str, default: str = "") -> str:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


class SmartRouteMeshTests(unittest.TestCase):
    def test_host_state_accepts_only_private_lan_and_cgnat_mesh(self) -> None:
        mesh_address = str(ipaddress.ip_address(0x64400508))
        non_lan_mesh_address = str(ipaddress.ip_address(0x64400009))
        state = normalize_host_smart_route(
            {
                "captured_at": 123,
                "lan_ipv4": [
                    "192.168.1.10",
                    "10.0.0.5",
                    "172.16.0.8",
                    "203.0.113.9",
                    non_lan_mesh_address,
                ],
                "mesh_installed": True,
                "mesh_online": True,
                "mesh_ipv4": mesh_address,
                "mesh_conflict": False,
                "mesh_version": "1.104.5",
            }
        )
        self.assertEqual(
            state["lan_ipv4"],
            ["192.168.1.10", "10.0.0.5", "172.16.0.8"],
        )
        self.assertTrue(state["mesh_online"])
        self.assertEqual(state["mesh_ipv4"], mesh_address)

        invalid = normalize_host_smart_route(
            {
                "mesh_online": True,
                "mesh_ipv4": "192.0.2.10",
            }
        )
        self.assertFalse(invalid["mesh_online"])
        self.assertEqual(invalid["mesh_ipv4"], "")

    def test_mesh_bootstrap_uses_bounded_root_helper_and_never_persists_key(self) -> None:
        registry = FakeRegistry()
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"auth_key": "hskey-auth-" + "A" * 32}),
            stderr="",
        )
        with patch(
            "hermes_rdp.smart_route.subprocess.run",
            return_value=completed,
        ) as run:
            result = create_mesh_bootstrap(registry, "connector")

        self.assertEqual(
            result["control_url"],
            "https://mesh.example.test",
        )
        self.assertTrue(result["auth_key"].startswith("hskey-auth-"))
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[:3], [
            "/usr/bin/sudo",
            "-n",
            "/usr/local/sbin/bakunity-rdp-mesh-key",
        ])
        self.assertEqual(args[3], "connector")
        self.assertNotIn("auth_key", registry.settings)

    def test_server_mesh_setup_is_pinned_hardened_and_health_gated(self) -> None:
        text = (
            ROOT / "scripts/setup-smart-route-mesh.sh"
        ).read_text(encoding="utf-8")
        for marker in (
            "HEADSCALE_VERSION=",
            "0.29.7",
            'MESH_HOST="mesh.$DEVICE_DOMAIN"',
            "DNS_NOT_READY:",
            "headscale configtest",
            'stun_listen_addr: "0.0.0.0:3478"',
            "urls: []",
            '"tag:bakunity-host"',
            '"tag:bakunity-connector"',
            '"ip": ["3389"]',
            "proxy_set_header Upgrade",
            'proxy_set_header Connection "upgrade";',
            "ufw allow 443/tcp",
            "ufw allow 3478/udp",
            'curl -fsS --max-time 3 "$CONTROL_URL/health"',
            '("smart_route_enabled", "1")',
            "SMART_ROUTE_MESH=PASS",
        ):
            self.assertIn(marker, text)

        enabled_index = text.index('("smart_route_enabled", "1")')
        health_index = text.index(
            'curl -fsS --max-time 3 "$CONTROL_URL/health"'
        )
        self.assertGreater(enabled_index, health_index)

    def test_controller_sandbox_allows_only_headscale_runtime_write_roots(self) -> None:
        service = (
            ROOT / "server/systemd/hermes-rdp.service"
        ).read_text(encoding="utf-8")
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ReadWritePaths=-/var/lib/headscale", service)
        self.assertIn("ReadWritePaths=-/var/run/headscale", service)

    def test_bounded_mesh_key_helper_allows_only_host_or_connector(self) -> None:
        helper = (
            ROOT / "server/bin/bakunity-rdp-mesh-key.sh"
        ).read_text(encoding="utf-8")
        sudoers = (
            ROOT / "server/sudoers/bakunity-rdp-mesh-key"
        ).read_text(encoding="utf-8")
        self.assertIn("--expiration 10m", helper)
        self.assertIn(
            'host) TAG="tag:bakunity-host,tag:bakunity-connector"',
            helper,
        )
        self.assertIn(
            'connector) TAG="tag:bakunity-connector"',
            helper,
        )
        self.assertIn(
            "/usr/local/sbin/bakunity-rdp-mesh-key host",
            sudoers,
        )
        self.assertIn(
            "/usr/local/sbin/bakunity-rdp-mesh-key connector",
            sudoers,
        )

    def test_windows_mesh_library_pins_signed_tailscale_and_protects_foreign_install(self) -> None:
        mesh = (
            ROOT / "client/BakunityMesh.ps1"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "$script:BakunityTailscaleVersion = '1.104.5'",
            "https://pkgs.tailscale.com/stable/tailscale-setup-$Version-$Arch.msi",
            "Get-AuthenticodeSignature",
            "FOREIGN_TAILSCALE",
            "owned.json",
            "--login-server=$ControlUrl",
            "--auth-key=file:$KeyFile",
            "--unattended",
            "--accept-dns=false",
            "--accept-routes=false",
            "--ssh=false",
            "--force-reauth",
            "tailscale unavailable",
            "via DERP",
            "via peer-relay",
        ):
            self.assertIn(marker, mesh)

    def test_connector_only_selects_p2p_after_direct_path_probe(self) -> None:
        worker = (
            ROOT / "client/BakunitySmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            "Test-BakunityMeshDirect -Target ([string]$P2p.host)",
            worker,
        )
        self.assertIn("if ($Path.direct)", worker)
        self.assertIn("reason='p2p_direct'", worker)
        self.assertIn("reason='vps_relay'", worker)
        self.assertIn("'DERP relay only'", worker)
        self.assertIn("Sync-ConnectorMesh", worker)

    def test_host_companion_is_separate_from_primary_agent(self) -> None:
        host = (
            ROOT / "client/BakunityHostSmartRoute.ps1"
        ).read_text(encoding="utf-8-sig")
        primary = (
            ROOT / "client/HermesRdpAgent.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("/smart-route-telemetry", host)
        self.assertIn("/smart-route-bootstrap", host)
        self.assertIn("Ensure-BakunityMeshRole -Role host", host)
        self.assertNotIn("Ensure-BakunityMeshRole", primary)

    def test_host_lifecycle_installs_smart_route_companion(self) -> None:
        install = (
            ROOT / "scripts/install-client.ps1"
        ).read_text(encoding="utf-8-sig")
        update = (
            ROOT / "scripts/update-client.ps1"
        ).read_text(encoding="utf-8-sig")
        repair = (
            ROOT / "scripts/repair-client.ps1"
        ).read_text(encoding="utf-8-sig")
        setup = (
            ROOT / "scripts/setup-smart-route-host.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("setup-smart-route-host.ps1", install)
        self.assertIn("setup-smart-route-host.ps1", update)
        self.assertIn("setup-smart-route-host.ps1", repair)
        self.assertIn("Smart Route Host deferred", install)
        self.assertIn("Smart Route Host deferred", update)
        self.assertIn("Smart Route Host deferred", repair)
        self.assertIn("Bakunity RDP Host Smart Route", setup)
        self.assertIn("BakunityMesh.ps1", setup)
        self.assertIn("HOST_SMART_ROUTE_SETUP=PASS", setup)

    def test_update_server_versions_and_deploys_mesh_components(self) -> None:
        update = (
            ROOT / "scripts/update-server.sh"
        ).read_text(encoding="utf-8")
        for marker in (
            '"client/BakunityMesh.ps1"',
            '"client/BakunityHostSmartRoute.ps1"',
            '"client/BakunitySmartRoute.ps1"',
            '"scripts/setup-smart-route-host.ps1"',
            "/usr/local/sbin/bakunity-rdp-mesh-key",
            "/etc/sudoers.d/bakunity-rdp-mesh-key",
        ):
            self.assertIn(marker, update)

    def test_api_exposes_authenticated_host_and_connector_bootstrap(self) -> None:
        api = (
            ROOT / "server/hermes_rdp/api.py"
        ).read_text(encoding="utf-8")
        for marker in (
            'path == "/v1/named-access/mesh-bootstrap"',
            'action == "smart-route-telemetry"',
            'action == "smart-route-bootstrap"',
            "create_mesh_bootstrap(",
            "get_host_smart_route(",
        ):
            self.assertIn(marker, api)


if __name__ == "__main__":
    unittest.main()
