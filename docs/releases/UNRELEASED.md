# Bakunity RDP — Unreleased

Base release: **v1.3.0**

Status: rolling engineering release ledger. Update continuously; do not wait until version-cut day.

## Merged / current main since v1.3.0

## Integration candidate

### Compatibility-safe Bakunity runtime surface

- Added public `bakunity-rdpctl` / `bakunity-rdp` entry points while retaining legacy `hermes_rdp`, systemd units, Windows Scheduled Tasks, local state paths and API identifiers for installed-agent compatibility.
- Server update now accepts `BAKUNITY_RDP_REF` with `HERMES_RDP_REF` as a backward-compatible fallback.
- Public release workflow and landing copy use Bakunity RDP branding; documentation explicitly identifies legacy Windows task names where operators must use the real installed identifiers.

### Zero-config server bootstrap

- Integrated the validated single-command bootstrap from PR #37 as `scripts/install.sh`.
- Keeps Telegram bot token entry masked, validates the bot and owner claim, resolves source immutably and preserves the existing advanced `install-server.sh` path.
- Trusted public-IP RDP certificate setup can coexist with nginx on TCP 80 through a managed ACME webroot and bounded rollback.

### Windows client lifecycle

- Integrated the live-validated lifecycle from PR #38 without replacing the accepted installer core.
- Same-server partial installs self-heal through Repair without new pairing or identity rotation.
- Different-server installs use transactional REPLACE with old-state rollback.
- Complete uninstall restores the pre-Bakunity RDP listener certificate binding, revokes server credentials, removes tasks/state and verifies local RDP remains available.
- Revoke verification normalizes already-revoked responses instead of reporting false failure after the server has already removed the device.

### Website and VPS migration preparation

- Added the Matrix hero animation and dark/green Bakunity presentation from the still-relevant parts of PR #40.
- Added `deploy/nginx-rdp.bakunity.com.conf` and a non-destructive VPS migration path; Vercel remains the active fallback until DNS/TLS/origin checks are completed.

### Vercel deployment filtering

- Fixed the public-site Git integration creating Vercel deployments for unrelated product/runtime/context commits.
- Vercel Git deployments are now disabled for every branch except `main`.
- `main` uses `VERCEL_GIT_PREVIOUS_SHA` and only continues the website build when `index.html`, `assets/**`, `robots.txt` or `site.webmanifest` changed.
- Existing Vercel security headers and redirects remain intact.
- A regression assertion in `tests/test_site_openssh_content.py` guards the branch and path filters.

### Automatic Windows client maintenance

- Added one-click Telegram Repair for maintenance-capable clients; legacy/offline clients keep the manual PowerShell fallback.
- The Windows Agent now receives the server's immutable `desired_client_ref` and automatically converges to that exact SHA instead of following mutable `main`.
- Automatic update/repair is deferred while any RDP session is active, so maintenance does not intentionally disconnect an in-use desktop.
- Added a separate `Hermes RDP Maintenance` SYSTEM task so Repair/Update survives stopping/restarting the main Agent task.
- Added bounded one-hour retry cooldown and an active-maintenance lock to prevent repair loops after failures.
- Trusted RDP certificate drift is checked on a cached 60-second path, outside the normal 3-second Agent control loop; unhealthy managed certificate state queues self-heal automatically.
- Fresh install, Repair and Update persist the current immutable client ref; uninstall removes the maintenance task and runtime state.
- Telegram device cards now expose client ref state, certificate lifecycle health and maintenance status, and refresh when those values change.

## Deferred observation / not a blocker

### Natural certificate renewal rotation

Synthetic drift/recovery is already live accepted. When the current production short-lived certificate renews naturally, capture only bounded evidence that:

- server state updates to the new thumbprint;
- Windows worker detects the new desired certificate;
- automatic rotation succeeds;
- a fresh Microsoft RDP connection remains trusted.

Do not force unnecessary production issuance solely to create this observation.

## Compatibility requirements carried forward

Do not regress:

- Windows PowerShell 5.1;
- Windows 10 x64 launched from x86/SysWOW64 PowerShell with Sysnative access to native OpenSSH;
- Windows Server support;
- Defender coexistence without exclusions/disablement;
- per-device Ed25519 identities;
- admin SSH isolation from Bakunity tunnel sshd;
- transactional server/client update rollback;
- existing-device Repair identity boundary;
- main Agent fast path without certificate work in the 3-second loop.

## Known historical deferred items

- `RL-006` remains PARTIAL only for an optional final Windows one-process observation after already-clean reconnect cycles; do not repeat the stress test.
- `SEC-004` remains fixture-unavailable; do not reconstruct revoked credentials solely for artificial evidence.

- Added stable per-device DNS slugs and optional wildcard device domains (for example `ai.tima.biz:53389`), with CLI management and DNS validation.

- Added Telegram editing for device display names/DNS slugs and per-device trusted certificates for named RDP endpoints.

- Added the Windows Named Access Connector for portless device hostnames on one public VPS IPv4, with independent read-only connector tokens and transactional local routing sync.

- Added automatic Named Access launcher fallback for Windows PCs that already own local TCP 3389; the installer now keeps local RDP untouched and installs a hostname-only Bakunity RDP launcher instead of failing.
