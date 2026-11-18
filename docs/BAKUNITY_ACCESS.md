# Bakunity Access architecture

Bakunity RDP now exposes two independent remote-access modes.

## Access modes

### Microsoft RDP

Use the native Windows Remote Desktop host when the installed Windows edition
supports incoming RDP:

- Windows Pro
- Windows Enterprise
- Windows Education
- Windows Server

The existing public per-device endpoint remains unchanged.

### Live Screen

Live Screen works with the currently logged-in interactive Windows session.
It is the fallback for Windows Home and an additional access mode on editions
that also support RDP.

Current v1 implementation:

- current desktop capture;
- multi-monitor virtual desktop snapshot;
- View Only by default in Web Admin;
- optional mouse and keyboard control;
- local Windows user remains in the current session;
- Windows helper listens only on 127.0.0.1;
- SSH exposes a second reverse-forward only on server 127.0.0.1;
- Web Admin token is required for screen and input API calls.

The internal Live Screen port is derived from the device RDP port:

    live_screen_server_port = rdp_port + 1000

The OpenSSH authorized-key command permits exactly two listeners for a device:
its public RDP listener and its private loopback Live Screen listener.

## Lifecycle

Fresh install, update, repair, uninstall and REPLACE all treat Live Screen as
part of the managed Windows client.

Windows Home skips RDP service/certificate operations but keeps the same
control-plane, OpenSSH, telemetry, maintenance and Live Screen lifecycle.

REPLACE still requires server-confirmed readiness before the old registration
is revoked:

- RDP-capable editions require the real server RDP listener;
- Home requires the real server Live Screen listener.

## Web Admin UX

A computer opens as a dedicated workspace instead of a side drawer.

The workspace separates:

- access methods;
- Live Screen;
- resource telemetry;
- agent/tunnel/endpoint health;
- routing;
- maintenance.

A device is considered accessible when at least one valid access method is
ready. Windows Home is not marked unhealthy merely because native RDP is
unsupported.

## Smart Route safety

Smart Route must fail open. A hostname may be mapped to 127.77.x.x only after
the corresponding local proxy is verified. If the local proxy cannot be
created, managed host mappings are removed so public DNS/relay remains usable.

## Next layers

These are architectural follow-ups, not fake UI controls:

1. Replace snapshot capture with DXGI Desktop Duplication and dirty-region
   updates for smoother display and lower bandwidth.
2. Add explicit Live Screen session IDs, start/stop audit events and operator
   attribution.
3. Add clipboard sync.
4. Add file transfer as a separate scoped capability.
5. Add terminal/PowerShell as a separate scoped capability.
6. Add roles and per-capability authorization (View, Control, Files, Terminal).
7. Add optional local session indicator/notification policy.
8. Add adaptive direct/relay transport for Live Screen data.
