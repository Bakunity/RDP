# Bakunity Transport

Bakunity Transport is the native connectivity layer for Bakunity RDP.

It is intentionally independent of Tailscale and Headscale. The existing
Tailscale/Headscale mesh remains a temporary compatibility fallback while the
native transport is rolled out and verified in production.

## Product model

Users work with two kinds of computers:

- **Target computer** — the Windows PC that exposes its local RDP service.
- **Source device** — the Windows PC from which the user starts Remote Desktop.

The Telegram UI uses product language such as **Компьютеры**,
**Откуда подключаюсь**, and **Подключение**. `host` and `connector` remain
internal implementation roles only.

Route policy is stored for each source-device -> target-computer pair.

## Route order

`AUTO` uses the first healthy route in this order:

1. `LAN DIRECT`
2. `BAKUNITY P2P`
3. `BAKUNITY RELAY`
4. legacy Tailscale mesh, while migration is in progress
5. existing OpenSSH `VPS RELAY`

Manual policies:

- `LAN` — local-network route only.
- `P2P` — native direct path only. It must not silently fall back to a relay.
- `RELAY` — force the existing OpenSSH VPS relay.
- `AUTO` — choose the best available route with safe fallback.

The original OpenSSH relay remains independent from Bakunity Transport so that
a transport failure cannot remove universal RDP access.

## Native data plane

The native executable is `bakunity-transport`.

It is a Go program built on go-libp2p and uses persistent Ed25519 peer
identities, encrypted connections, TCP/QUIC, NAT port mapping, Circuit Relay
v2, and hole punching for direct peer connectivity.

RDP uses the dedicated `/bakunity/rdp/1.0.0` stream protocol. The target peer
bridges an authenticated stream only to `127.0.0.1:3389`.

The source peer exposes per-target loopback listeners. Existing Smart Route
hostname/portproxy logic sends ordinary `mstsc.exe` traffic into those local
listeners.

## Authorization

Libp2p peer identity is not sufficient authorization by itself.

Two additional controls are required:

1. The VPS relay admits only peer IDs reported by authenticated Bakunity API
   clients. Relay admission control is bound to localhost only.
2. Each target computer has a separate random shared secret. RDP streams carry
   an HMAC-SHA256 proof tied to the source peer ID before the target opens its
   local RDP socket.

The target secret is delivered only through the authenticated and pinned
Bakunity control plane to an authorized source device.

## VPS relay

The VPS relay listens publicly on TCP/UDP 7444 and exposes control only on
`127.0.0.1:7445`. It runs as the unprivileged `bakunity-transport` user with
a hardened systemd sandbox and bounded Circuit Relay resources.

The reliable bootstrap address uses TCP. QUIC remains available for direct
peer connectivity and future relay transport evolution.

## Windows runtime

Windows receives `BakunityNativeTransport.ps1`, which resolves an immutable
repository SHA, downloads a pinned Go toolchain, verifies its SHA-256, builds
the native executable, protects runtime files under
`C:\ProgramData\BakunityRDP\Transport`, creates executable-scoped firewall
rules, and runs the transport under SYSTEM.

This build-on-device mechanism is the first deployment path. A signed pre-built
`BakunityTransport.exe` should replace it once the release pipeline publishes
signed binaries.

## Host lifecycle

The existing primary RDP agent remains separate. The Host Smart Route companion
reports transport state, requests bootstrap data, installs the native peer,
reports its peer ID, and lets the coordinator admit that peer to the relay.

If native transport fails, the original RDP agent and OpenSSH tunnel continue
working.

## Source-device lifecycle

The Smart Route source device starts Bakunity Transport, reports its peer ID,
receives per-target peer IDs and stream secrets, creates loopback forwards,
and reports the actual selected route back to the control plane.

## Migration away from Tailscale

The migration is incremental: native transport is deployed alongside the
existing mesh, `AUTO` prefers Bakunity Transport, real direct/relay behavior
is verified, and then Headscale/Tailscale bootstrap/runtime code can be
removed without changing Telegram UX or the independent OpenSSH fallback.

Tailscale is therefore a temporary migration fallback, not a protocol or
product dependency of Bakunity Transport.
