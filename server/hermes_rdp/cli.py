from __future__ import annotations

import argparse
import ipaddress
import json
import secrets
import socket
import ssl
import subprocess
import time
import urllib.request

from .config import load_config
from .db import Registry
from .tunnel import close_tunnel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bakunity-rdpctl")
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="manage one-time pairing codes")
    pair_sub = pair.add_subparsers(dest="pair_command", required=True)
    pair_create = pair_sub.add_parser("create")
    pair_create.add_argument("--name")
    pair_create.add_argument("--port", type=int)
    pair_create.add_argument("--slug")
    pair_create.add_argument("--ttl", type=int, default=900)

    devices = sub.add_parser("devices")
    devices_sub = devices.add_subparsers(dest="devices_command", required=True)
    devices_sub.add_parser("list")
    device_delete = devices_sub.add_parser("delete")
    device_delete.add_argument("device_id")
    device_rename = devices_sub.add_parser("rename")
    device_rename.add_argument("device_id")
    device_rename.add_argument("name")
    device_slug = devices_sub.add_parser("slug")
    device_slug.add_argument("device_id")
    device_slug.add_argument("slug")

    domain = sub.add_parser("domain", help="manage wildcard device domain")
    domain_sub = domain.add_subparsers(dest="domain_command", required=True)
    domain_set = domain_sub.add_parser("set")
    domain_set.add_argument("domain")
    domain_sub.add_parser("show")
    domain_sub.add_parser("status")
    domain_sub.add_parser("clear")

    dashboard = sub.add_parser("dashboard")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_command", required=True)
    dashboard_sub.add_parser("reset")

    auth = sub.add_parser("authorized-key")
    auth.add_argument("username")
    auth.add_argument("key_type")
    auth.add_argument("key_blob")

    sub.add_parser("doctor")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config()
    registry = Registry(
        config.db_path,
        config.port_start,
        config.port_end,
        config.command_timeout_seconds,
    )

    if args.command == "pair" and args.pair_command == "create":
        code = registry.create_pair_code(
            display_name=args.name,
            preferred_port=args.port,
            slug=args.slug,
            ttl_seconds=args.ttl,
        )
        print(f"PAIR_CODE={code}")
        print(f"EXPIRES_IN={args.ttl}")
        print(f"SERVER={config.public_host}")
        print(f"FINGERPRINT={config.tls_fingerprint}")
        return

    if args.command == "devices" and args.devices_command == "list":
        device_domain = registry.get_device_domain()
        for device in registry.list_devices():
            age = (
                "never"
                if not device.get("last_seen")
                else str(int(time.time()) - int(device["last_seen"]))
            )
            key_state = "ssh-key=yes" if device.get("ssh_public_key") else "ssh-key=no"
            slug = str(device.get("slug") or "")
            host = (
                f"{slug}.{device_domain}"
                if slug and device_domain
                else config.public_host
            )
            print(
                f"{device['id']}\t{device['display_name']}\t{device['machine_name']}\t"
                f"{slug or '-'}\t{host}:{device['rdp_port']}\t"
                f"{key_state}\tlast_seen={age}s"
            )
        return

    if args.command == "devices" and args.devices_command == "delete":
        device = registry.get_device(args.device_id)
        registry.revoke_device(args.device_id)
        try:
            close_tunnel(config, int(device["rdp_port"]))
        except Exception as exc:
            print(f"WARNING: tunnel close failed: {exc}")
        print("OK")
        return

    if args.command == "devices" and args.devices_command == "rename":
        registry.rename_device(args.device_id, args.name)
        print("OK")
        return

    if args.command == "devices" and args.devices_command == "slug":
        slug = registry.set_device_slug(args.device_id, args.slug)
        domain = registry.get_device_domain()
        print(f"SLUG={slug}")
        if domain:
            print(f"HOST={slug}.{domain}")
        print("OK")
        return

    if args.command == "domain":
        if args.domain_command == "set":
            domain = registry.set_device_domain(args.domain)
            print(f"DEVICE_DOMAIN={domain}")
            print(f"DNS_REQUIRED=A * -> {config.public_host}")
            print("NOTE=Wildcard DNS removes per-device DNS work; RDP port remains until a gateway is enabled.")
            return

        if args.domain_command == "show":
            domain = registry.get_device_domain()
            print(f"DEVICE_DOMAIN={domain or 'disabled'}")
            return

        if args.domain_command == "clear":
            registry.clear_device_domain()
            print("DEVICE_DOMAIN=disabled")
            print("OK")
            return

        if args.domain_command == "status":
            domain = registry.get_device_domain()
            if not domain:
                print("DEVICE_DOMAIN=disabled")
                raise SystemExit(1)

            probe = f"bakunity-{secrets.token_hex(4)}.{domain}"

            def resolve(host: str) -> set[str]:
                try:
                    ipaddress.ip_address(host)
                    return {host}
                except ValueError:
                    pass
                return {
                    row[4][0]
                    for row in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
                }

            try:
                server_addresses = resolve(config.public_host)
            except OSError as exc:
                print(f"SERVER_DNS=FAIL ({exc})")
                raise SystemExit(1)

            try:
                probe_addresses = resolve(probe)
            except OSError as exc:
                print(f"DEVICE_DOMAIN={domain}")
                print(f"PROBE={probe}")
                print(f"WILDCARD_DNS=FAIL ({exc})")
                raise SystemExit(1)

            match = sorted(server_addresses & probe_addresses)
            print(f"DEVICE_DOMAIN={domain}")
            print(f"PROBE={probe}")
            print(f"SERVER_ADDRESSES={','.join(sorted(server_addresses))}")
            print(f"PROBE_ADDRESSES={','.join(sorted(probe_addresses))}")
            print(f"WILDCARD_DNS={'PASS' if match else 'MISMATCH'}")
            if not match:
                raise SystemExit(1)
            return

    if args.command == "dashboard" and args.dashboard_command == "reset":
        registry.set_setting("dashboard_message_id", "")
        registry.set_setting("screen", "home")
        registry.set_setting("selected_device", "")
        print("Dashboard state reset. Send /start to the bot.")
        return

    if args.command == "authorized-key":
        device = registry.authorize_ssh_key(args.key_type, args.key_blob)
        if device and args.username == config.ssh_user:
            port = int(device["rdp_port"])
            options = (
                "no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc,"
                f'permitlisten="0.0.0.0:{port}"'
            )
            print(
                f"{options} {device['ssh_public_key']} "
                f"hermes-rdp-{device['id']}"
            )
        return

    if args.command == "doctor":
        errors = 0
        print(f"config: OK ({config.public_host})")
        print(f"database: OK ({config.db_path})")
        device_domain = registry.get_device_domain()
        print(f"device-domain: {device_domain or 'disabled'}")
        try:
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(
                f"https://127.0.0.1:{config.api_port}/healthz",
                context=context,
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            print(f"api: OK ({payload.get('version')}, {payload.get('tunnel')})")
        except Exception as exc:
            errors += 1
            print(f"api: FAIL ({exc})")
        for port, name in [
            (config.ssh_bind_port, "ssh-tunnel"),
            (config.api_port, "api"),
        ]:
            sock = socket.socket()
            sock.settimeout(2)
            try:
                sock.connect(("127.0.0.1", port))
                print(f"{name}: LISTEN {port}")
            except OSError as exc:
                errors += 1
                print(f"{name}: FAIL {port} ({exc})")
            finally:
                sock.close()
        try:
            completed = subprocess.run(
                ["/usr/sbin/sshd", "-t", "-f", "/etc/hermes-rdp/sshd_config"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed.returncode:
                raise RuntimeError((completed.stderr or completed.stdout).strip())
            print("ssh-config: OK")
        except Exception as exc:
            errors += 1
            print(f"ssh-config: FAIL ({exc})")
        if errors:
            raise SystemExit(1)
        return


if __name__ == "__main__":
    main()
