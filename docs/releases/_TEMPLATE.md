# Bakunity RDP vX.Y.Z — <short release title>

One short paragraph: what this release is and why it matters.

## Главное

Keep this to roughly 8–12 concrete bullets:

- major product capability;
- major reliability/recovery change;
- important compatibility fix;
- important bug/root-cause closure;
- lifecycle/security change;
- visible Telegram/UI improvement;
- important documentation/testing update.

## Проверено

Keep only the most useful live/CI acceptance bullets, for example:

- external RDP / fresh install;
- reboot/reconnect;
- update/rollback or Repair;
- important Windows compatibility;
- relevant CI/release checks.

## Breaking changes / recommendation

Only include this section when useful. State migrations, avoided tags or the recommended version clearly.

**Полная инженерная история:** [vX.Y.Z-full.md](https://github.com/bakunity/RDP/blob/main/docs/releases/history/vX.Y.Z-full.md)

Do not put several paragraphs of root-cause analysis into this public file. Detailed bugs, evidence, test matrices, CI provenance and deferred observations belong in `history/vX.Y.Z-full.md` and `context/EVIDENCE_LEDGER.md`.
