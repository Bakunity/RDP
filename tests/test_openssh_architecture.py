from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OpenSshArchitectureTests(unittest.TestCase):
    def test_windows_installer_uses_only_windows_openssh(self) -> None:
        text = (ROOT / "scripts/install-client-core.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("OpenSSH.Client", text)
        self.assertIn("ssh-keygen.exe", text)
        self.assertIn("ssh_public_key", text)
        self.assertIn("known_hosts", text)
        self.assertIn(
            "StrictHostKeyChecking",
            (ROOT / "client/HermesRdpAgent.ps1").read_text(encoding="utf-8-sig"),
        )
        forbidden = (
            "fatedier/frp",
            "frp.zip",
            "Get-FileHash",
            "Add-MpPreference",
            "ExclusionPath",
        )
        for value in forbidden:
            self.assertNotIn(value, text)

    def test_agent_runs_restricted_reverse_ssh_tunnel(self) -> None:
        text = (ROOT / "client/HermesRdpAgent.ps1").read_text(encoding="utf-8-sig")
        for value in (
            "ExitOnForwardFailure=yes",
            "BatchMode=yes",
            "StrictHostKeyChecking=yes",
            "UserKnownHostsFile=",
            "0.0.0.0:$($Config.rdp_port):127.0.0.1:3389",
            "ssh_tunnel_running",
        ):
            self.assertIn(value, text)
        self.assertNotIn("frpc.exe", text)
        self.assertNotIn("frpc_running", text)

    def test_server_has_isolated_openssh_daemon_and_key_restrictions(self) -> None:
        text = (ROOT / "scripts/install-server.sh").read_text(encoding="utf-8")
        for value in (
            "openssh-server",
            "AuthorizedKeysCommand /usr/local/bin/hermes-rdp-authorized-keys %u %t %k",
            "AuthorizedKeysCommandUser hermes-rdp",
            "AllowTcpForwarding remote",
            "GatewayPorts clientspecified",
            "MaxSessions 0",
            "PasswordAuthentication no",
            "AuthenticationMethods publickey",
            "hermes-rdp-sshd.service",
        ):
            self.assertIn(value, text)
        self.assertNotIn("github.com/fatedier/frp", text)
        self.assertNotIn("FRP_VERSION", text)

        auth = (ROOT / "server/hermes_rdp/authorized_keys.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('permitlisten="0.0.0.0:{port}"', auth)
        self.assertIn("no-agent-forwarding", auth)
        self.assertIn("no-pty", auth)

    def test_legacy_frp_service_is_not_shipped(self) -> None:
        self.assertFalse((ROOT / "server/systemd/frps.service").exists())
        service = ROOT / "server/systemd/hermes-rdp-sshd.service"
        self.assertTrue(service.is_file())
        self.assertIn("sshd -D", service.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
