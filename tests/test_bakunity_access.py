from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BakunityAccessTests(unittest.TestCase):
    def test_windows_home_falls_back_to_live_screen_instead_of_failing(self) -> None:
        install = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$RdpSupported = [bool](", install)
        self.assertIn("$Os.Caption -match 'Pro|Enterprise|Education'", install)
        self.assertIn("Bakunity Live Screen", install)
        self.assertIn("rdp_supported = [bool]$RdpSupported", install)
        self.assertIn("live_screen_local_port = 48400", install)
        self.assertIn("setup-access-host.ps1", install)
        self.assertNotIn(
            "не поддерживает входящие RDP-подключения",
            install,
        )

    def test_live_screen_host_is_loopback_only_and_supports_view_and_control(self) -> None:
        host = (ROOT / "client/BakunityAccessHost.ps1").read_text(
            encoding="utf-8-sig"
        )
        for marker in (
            "[Net.IPAddress]::Loopback",
            "$Port = 48400",
            "SNAPSHOT",
            "INPUT",
            "CopyFromScreen",
            "image/jpeg",
            "SendInput",
            "MoveAbsolute",
            "MouseButton",
            "Wheel",
            "Text(string text)",
        ):
            self.assertIn(marker, host)
        self.assertNotIn("[Net.IPAddress]::Any", host)

    def test_system_agent_launches_access_host_in_interactive_session(self) -> None:
        agent = (ROOT / "client/HermesRdpAgent.ps1").read_text(
            encoding="utf-8-sig"
        )
        for marker in (
            "WTSGetActiveConsoleSessionId",
            "WTSQueryUserToken",
            "CreateProcessAsUser",
            'si.lpDesktop = "winsta0\\\\default"',
            "function Ensure-AccessHost",
            "$AccessHostPort = 48400",
            "live_screen_capable",
            "live_screen_running",
        ):
            self.assertIn(marker, agent)

    def test_ssh_exposes_rdp_publicly_but_live_screen_only_to_server_loopback(self) -> None:
        agent = (ROOT / "client/HermesRdpAgent.ps1").read_text(
            encoding="utf-8-sig"
        )
        auth = (ROOT / "server/hermes_rdp/authorized_keys.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "0.0.0.0:$($Config.rdp_port):127.0.0.1:3389",
            agent,
        )
        self.assertIn(
            "127.0.0.1:$(Get-AccessServerPort):127.0.0.1:$AccessHostPort",
            agent,
        )
        self.assertIn('permitlisten="0.0.0.0:{port}"', auth)
        self.assertIn(
            'permitlisten="127.0.0.1:{access_port}"',
            auth,
        )

    def test_server_admin_is_required_for_screen_and_input(self) -> None:
        api = (ROOT / "server/hermes_rdp/api.py").read_text(encoding="utf-8")
        for marker in (
            "def _admin_screen(",
            "def _admin_screen_input(",
            "if not self._admin_auth():",
            'socket.create_connection(("127.0.0.1", port)',
            'sock.sendall(b"PING\\n")',
            'return response == b"OK"',
            '"rdp_endpoint_available": rdp_state',
            '"live_screen_endpoint_available": live_screen_state',
            "screen-input",
        ):
            self.assertIn(marker, api)

    def test_device_ui_is_full_page_and_defaults_to_view_only(self) -> None:
        web = (ROOT / "server/hermes_rdp/admin_web.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            'id="page-device"',
            'id="liveStage"',
            "function renderDevice()",
            "function startLive(control)",
            "function setLiveControl(v)",
            "LIVE_CONTROL=false",
            "View Only",
            "Только просмотр",
            "Windows Home не принимает входящие Microsoft RDP",
        ):
            self.assertIn(marker, web)
        self.assertNotIn('id="drawerBack"', web)
        self.assertNotIn("function renderDrawer()", web)
        for legacy_glyph in ("⌂", "▣", "＋", "◫", "↻", "✕", "☰"):
            self.assertNotIn(legacy_glyph, web)

    def test_update_and_repair_manage_access_host_lifecycle(self) -> None:
        update = (ROOT / "scripts/update-client.ps1").read_text(
            encoding="utf-8-sig"
        )
        repair = (ROOT / "scripts/repair-client.ps1").read_text(
            encoding="utf-8-sig"
        )
        repair_core = (ROOT / "scripts/repair-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        for text in (update, repair):
            self.assertIn("setup-access-host.ps1", text)
            self.assertIn("LiveScreen", text)
        self.assertIn("$AccessHostExistedBefore", update)
        self.assertIn("$BackupAccessHost", update)
        self.assertIn("$RdpSupported", repair_core)

    def test_server_update_versions_access_bundle_and_close_helper(self) -> None:
        update = (ROOT / "scripts/update-server.sh").read_text(
            encoding="utf-8"
        )
        install = (ROOT / "scripts/install-server.sh").read_text(
            encoding="utf-8"
        )
        helper = (ROOT / "server/bin/hermes-rdp-close-tunnel.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            '"client/BakunityAccessHost.ps1"',
            '"scripts/setup-access-host.ps1"',
            "server/bin/hermes-rdp-close-tunnel.sh",
        ):
            self.assertIn(marker, update)
        self.assertIn("server/bin/hermes-rdp-close-tunnel.sh", install)
        self.assertIn("ACCESS_START=$((START + 1000))", helper)
        self.assertIn("ACCESS_END=$((END + 1000))", helper)


if __name__ == "__main__":
    unittest.main()
