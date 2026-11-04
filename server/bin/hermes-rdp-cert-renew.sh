#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG=/etc/hermes-rdp/config.json
CERTBOT=/usr/local/bin/certbot
STATE_REFRESH=/usr/local/sbin/hermes-rdp-cert-state-refresh
LOCK=/run/hermes-rdp-cert-renew.lock

if [[ ! -x "$CERTBOT" ]]; then
  echo "Hermes certificate renewal: certbot is unavailable at $CERTBOT" >&2
  exit 1
fi
if [[ ! -x "$STATE_REFRESH" ]]; then
  echo "Hermes certificate renewal: state refresher is unavailable at $STATE_REFRESH" >&2
  exit 1
fi
if [[ ! -s "$CONFIG" ]]; then
  echo "Hermes certificate renewal: missing $CONFIG" >&2
  exit 1
fi
if ! command -v flock >/dev/null 2>&1; then
  echo "Hermes certificate renewal: flock is unavailable" >&2
  exit 1
fi

exec 9>"$LOCK"
if ! /usr/bin/flock -w 300 9; then
  echo "Hermes certificate renewal: timed out waiting for lock" >&2
  exit 1
fi

"$CERTBOT" renew \
  --quiet \
  --non-interactive

# The legacy public-IP state remains useful for installations without a
# device domain. Per-device domain certificate metadata is read directly from
# each Certbot lineage by the bounded package helper.
"$STATE_REFRESH" >/dev/null
