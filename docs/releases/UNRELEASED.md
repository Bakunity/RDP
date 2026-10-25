# Bakunity RDP — Unreleased

Base release: **v1.3.0**

Status: rolling engineering release ledger. Update continuously; do not wait until version-cut day.

## Merged / current main since v1.3.0

### Vercel deployment filtering

- Fixed the public-site Git integration creating Vercel deployments for unrelated product/runtime/context commits.
- Vercel Git deployments are now disabled for every branch except `main`.
- `main` uses `VERCEL_GIT_PREVIOUS_SHA` and only continues the website build when `index.html`, `assets/**`, `robots.txt` or `site.webmanifest` changed.
- Existing Vercel security headers and redirects remain intact.
- A regression assertion in `tests/test_site_openssh_content.py` guards the branch and path filters.

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
