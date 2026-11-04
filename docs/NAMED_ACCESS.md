# Named Access

Named Access removes the visible per-device RDP port while keeping the existing
Bakunity RDP reverse-OpenSSH transport and one public VPS IPv4.

After the Connector is installed on the Windows PC that initiates RDP
connections, Microsoft Remote Desktop can use:

```text
mipc.tima.biz
bfsrv.tima.biz
revit.tima.biz
```

instead of:

```text
mipc.tima.biz:53389
bfsrv.tima.biz:53397
revit.tima.biz:53394
```

The direct `hostname:port` endpoint remains available as a fallback.

## Why a Connector is required

Raw RDP to one IPv4 address does not provide Bakunity RDP with a reliable
hostname routing key before the TCP connection reaches a device-specific
listener. DNS can point every device hostname at the VPS, but DNS alone cannot
choose between ports 53389, 53390, and so on.

Named Access therefore performs the final routing step on the initiating
Windows PC.

## Architecture

Named Access has two automatic Windows routing modes.

### Transparent mode

If local TCP 3389 is free, each device receives a stable loopback IPv4 address
from the Bakunity pool `127.77.0.0/16`.

```text
mipc.tima.biz
  -> Windows hosts: 127.77.0.1
  -> local TCP 127.77.0.1:3389
  -> Windows portproxy
  -> SERVER_IP_OR_DOMAIN:53389
  -> existing Bakunity reverse SSH tunnel
  -> MIPC:3389
```

The user can type `mipc.tima.biz` directly into Microsoft Remote Desktop.

### Launcher mode

If the initiating Windows PC already owns TCP 3389 because it is itself an RDP
host, the installer automatically selects launcher mode. It does not disable or
move the local RDP listener.

The background task keeps a read-only local cache of `hostname -> RDP port`.
The **Bakunity RDP** Start Menu shortcut asks only for the Bakunity device name,
for example `mipc.tima.biz` or simply `mipc`, and starts Microsoft Remote
Desktop with the correct endpoint internally.

The user never needs to enter the numeric Bakunity RDP port.

In both modes the remote hostname remains the certificate identity, so the
per-device Let's Encrypt certificate continues to match the device hostname.
The existing direct `hostname:port` endpoint remains available as a fallback.

## Server setup

The device domain must already be configured:

```bash
sudo bakunity-rdpctl domain status
```

Create an independent read-only Connector credential:

```bash
sudo bakunity-rdpctl named-access create --name "Main Windows PC"
```

The command prints a `POWERSHELL_ADMIN_COMMAND`. Run that command in an
elevated Windows PowerShell on the computer from which RDP connections will be
started.

The install command contains a secret read-only token. Do not publish or paste
it into issue trackers, chats, screenshots, or logs.

## Connector lifecycle

List active Connectors:

```bash
sudo bakunity-rdpctl named-access list
```

Revoke one Connector without affecting others:

```bash
sudo bakunity-rdpctl named-access revoke CONNECTOR_ID
```

The server stores only a SHA-256 hash of each Connector token.

## Windows behavior

The Connector installs:

```text
C:\ProgramData\BakunityRDP\NamedAccess\
Bakunity RDP Named Access   (Scheduled Task, LocalSystem)
Bakunity RDP                (Start Menu shortcut)
```

The installer automatically reports either `ROUTING_MODE=portproxy` or
`ROUTING_MODE=launcher`.

The worker:

- authenticates to the pinned Bakunity HTTPS API;
- reads a read-only `slug -> port` manifest;
- owns only the marked Bakunity block in the Windows hosts file;
- owns only loopback listeners from `127.77.0.0/16`;
- synchronizes only when hostname/IP/port mappings actually change;
- leaves unrelated hosts entries and unrelated portproxy rules untouched;
- automatically learns newly added devices and slug changes.

If TCP 3389 is already occupied by a normal local RDP listener on the initiating
PC, the Connector automatically uses launcher mode. It never disables or moves
the PC's local RDP service.

## Verification

After installation:

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Named Access' | Select-Object TaskName,State
Get-Content 'C:\ProgramData\BakunityRDP\NamedAccess\state.json' -Raw
```

For transparent mode, `ping -4 mipc.tima.biz` should resolve locally to
`127.77.x.x`, and Microsoft Remote Desktop can use `mipc.tima.biz` directly.

For launcher mode, open **Bakunity RDP** from the Start Menu and enter:

```text
mipc.tima.biz
```

or simply:

```text
mipc
```

## Manual sync

The background task normally synchronizes every 60 seconds. For an immediate
one-time check:

```powershell
& 'C:\ProgramData\BakunityRDP\NamedAccess\BakunityNamedAccess.ps1' -Once
```

## Uninstall

Run the repository `scripts/uninstall-named-access.ps1` script as
Administrator. It removes only the recorded Named Access loopback routes, the
managed hosts block, the Scheduled Task, the Start Menu shortcut, and the Named
Access directory.

The server-side token remains valid until it is explicitly revoked with
`bakunity-rdpctl named-access revoke CONNECTOR_ID`.
