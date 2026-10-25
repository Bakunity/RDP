# Bakunity RDP release notes

Release history has **two layers**:

1. `docs/releases/vX.Y.Z.md` — concise public GitHub Release description.
2. `docs/releases/history/vX.Y.Z-full.md` — full engineering history: bugs, root causes, acceptance, CI, compatibility and deferred items.

GitHub Release descriptions are synchronized from the concise `vX.Y.Z.md` files. Detailed evidence is never supposed to be pasted as one huge public release body.

## Files

- `UNRELEASED.md` — detailed rolling ledger for the next release.
- `_TEMPLATE.md` — concise public release template.
- `vX.Y.Z.md` — concise public release notes.
- `history/vX.Y.Z-full.md` — detailed permanent engineering history.

## Working rule

Do not wait until release day to reconstruct the release from memory.

During development, keep `UNRELEASED.md` detailed: record meaningful product work, confirmed bugs/root causes, live PASS/FAIL, compatibility, security, docs and deferred items.

Before release:

1. reconcile `UNRELEASED.md` with `context/EVIDENCE_LEDGER.md`, merged PRs and CI;
2. create/update `history/vX.Y.Z-full.md` with the complete engineering record;
3. create `vX.Y.Z.md` as a **short readable summary**, normally a headline, 8–12 main bullets, a compact validation block and links to full history/evidence;
4. update `CHANGELOG.md` with an even shorter index-level summary;
5. validate the final release tree and publish from exact validated workflow HEAD.

## Public release size rule

A GitHub Release should not become a wall of text.

Prefer:

- one short intro;
- one `Главное` section;
- one compact `Проверено` section;
- compatibility/breaking note only when needed;
- link to the full engineering history.

If a detail needs several paragraphs, it belongs in `history/`, not in the public Release body.

## Historical corrections

Published release descriptions may be corrected or expanded, but existing Git tags are never rewritten. Do not retroactively claim functionality that was implemented only after that release tree.

## GitHub Release synchronization

`.github/workflows/release.yml` treats `docs/releases/vX.Y.Z.md` as the public Release-body source of truth:

- new releases are created from that file;
- existing current releases are synchronized from that file;
- changed historical `vX.Y.Z.md` files update the matching GitHub Release without moving the tag.

The detailed `history/` files are intentionally not auto-published as the Release body.

## Security / privacy

Never store pairing codes, API/device tokens, private keys, PFX passwords/material, Telegram owner IDs or other secrets in release history.
