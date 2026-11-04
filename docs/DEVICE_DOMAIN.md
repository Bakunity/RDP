# Device domains and automatic DNS names

Bakunity RDP can assign a stable DNS label to every registered device.

Example with the base domain `tima.biz`:

```text
AI            -> ai.tima.biz:53389
Tima PC       -> tima-pc.tima.biz:53390
Office        -> office.tima.biz:53391
```

The device label (slug) is stored in the Bakunity RDP database and remains
stable when the friendly display name is changed.

## One-time DNS setup

Create one wildcard DNS record at the DNS provider that hosts the zone:

```text
Type: A
Name/Host: *
Value: <public IPv4 of the Bakunity RDP VPS>
TTL: 300 or Auto
```

For providers that support HTTP proxying (for example Cloudflare), the record
must be DNS-only for raw RDP traffic.

An explicit DNS record such as `www.tima.biz` or `api.tima.biz` still takes
precedence over the wildcard. The wildcard therefore handles only names that do
not already have their own record.

No per-device DNS API integration is required. Once the wildcard exists,
`anything.tima.biz` resolves to the VPS automatically.

## Enable the device domain

On the Bakunity RDP server:

```bash
sudo bakunity-rdpctl domain set tima.biz
sudo bakunity-rdpctl domain status
```

The status command resolves a random wildcard name and compares it with the
configured Bakunity RDP server address.

Show or remove the setting:

```bash
sudo bakunity-rdpctl domain show
sudo bakunity-rdpctl domain clear
```

## Device slugs

Slugs are generated automatically when a device is paired. Conflicts receive a
numeric suffix:

```text
ai
ai-2
ai-3
```

A specific slug can be reserved when creating a pair code:

```bash
sudo bakunity-rdpctl pair create --name 'Tima PC' --slug tima
```

Or changed later:

```bash
sudo bakunity-rdpctl devices slug DEVICE_ID tima
```

List current names and endpoints:

```bash
sudo bakunity-rdpctl devices list
```

## Current routing limitation

The wildcard domain removes manual DNS management, but it does not by itself
remove the numeric RDP port.

With one public IPv4, both `tima.tima.biz` and `ai.tima.biz` reach the same
server IP. Standard raw RDP does not provide a reliable hostname routing key
that can be used to map multiple hostnames on the same TCP port 3389 to
different reverse tunnels.

Therefore the current supported named endpoint is:

```text
<slug>.tima.biz:<assigned-port>
```

A future Named Access / gateway layer can hide the per-device port. The
database slug/domain model introduced here is intentionally designed to be
reused by that gateway later.


## Trusted RDP certificates for named devices

When a device domain is enabled, Bakunity RDP uses a separate trusted
certificate for each device hostname instead of reusing the legacy public-IP
certificate.

Example:

```text
mipc.tima.biz  -> its own certificate
bfsrv.tima.biz -> its own certificate
```

The certificate helper derives the hostname from the authenticated device ID,
its stored slug and the configured device domain. It does not accept an
arbitrary hostname from the client.

Existing devices can be provisioned immediately after enabling the domain:

```bash
sudo bakunity-rdpctl certificates sync
sudo bakunity-rdpctl certificates status
```

After the server certificate exists, the existing Windows certificate rotation
task detects the new thumbprint and installs/binds the matching certificate.
Changing a device slug causes the same per-device Certbot lineage to be updated
for the new hostname.

HTTP-01 validation requires TCP 80 to reach this VPS. In nginx webroot mode,
Bakunity RDP installs a managed wildcard server_name route only for the ACME
challenge path under the configured device domain. Exact nginx virtual hosts
continue to take precedence.

## Editing names in Telegram

Open a computer in the Telegram bot. The compact card exposes:

- `ИМЯ` — changes the friendly display name;
- `АДРЕС` — changes the stable DNS slug before the base domain.

For example, changing the address to `tima` with `tima.biz` configured makes
the endpoint `tima.tima.biz:<port>`. The RDP port remains unchanged.
