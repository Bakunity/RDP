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

For each device the Connector assigns a stable loopback IPv4 address from the
private-to-the-machine Bakunity pool `127.77.0.0/16`.

Example:

```text
mipc.tima.biz
  -> Windows hosts: 127.77.0.1
  -> local TCP 127.77.0.1:3389
  -> Windows portproxy
  -> SERVER_IP_OR_DOMAIN:53389
  -> existing Bakunity reverse SSH tunnel
  -> MIPC:3389
```

The RDP client still connects using the hostname `mipc.tima.biz`, so the
per-device Let's Encrypt certificate remains matched to that hostname.

Bakunity RDP currently transports the device leg over TCP/OpenSSH, therefore
the Connector also uses TCP portproxy. It does not open a new public port and
does not change the remote Windows device.

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
```

The worker:

- authenticates to the pinned Bakunity HTTPS API;
- reads a read-only `slug -> port` manifest;
- owns only the marked Bakunity block in the Windows hosts file;
- owns only loopback listeners from `127.77.0.0/16`;
- synchronizes only when hostname/IP/port mappings actually change;
- leaves unrelated hosts entries and unrelated portproxy rules untouched;
- automatically learns newly added devices and slug changes.

If TCP 3389 is already occupied by a normal local RDP listener on the initiating
PC, the Connector fails closed. It does not disable or move the PC's local RDP
service automatically.

## Verification

After installation:

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Named Access' | Select-Object TaskName,State
ping -4 mipc.tima.biz
netsh interface portproxy show v4tov4
```

The device hostname should resolve locally to `127.77.x.x`.

Then open Microsoft Remote Desktop and enter only:

```text
mipc.tima.biz
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
managed hosts block, the Scheduled Task, and the Named Access directory.

The server-side token remains valid until it is explicitly revoked with
`bakunity-rdpctl named-access revoke CONNECTOR_ID`.
