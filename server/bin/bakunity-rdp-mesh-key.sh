#!/usr/bin/env bash
set -Eeuo pipefail

MARKER=/etc/hermes-rdp/smart-route-mesh.enabled
HEADSCALE=/usr/bin/headscale

if (($# != 1)); then
  echo "usage: bakunity-rdp-mesh-key host|connector" >&2
  exit 2
fi

case "$1" in
  host) TAG="tag:bakunity-host,tag:bakunity-connector" ;;
  connector) TAG="tag:bakunity-connector" ;;
  *) echo "invalid mesh role" >&2; exit 2 ;;
esac

[[ -s "$MARKER" ]] || {
  echo "Smart Route mesh is not enabled" >&2
  exit 3
}
[[ -x "$HEADSCALE" ]] || {
  echo "headscale is not installed" >&2
  exit 4
}

KEY="$("$HEADSCALE" preauthkeys create --tags "$TAG" --expiration 10m 2>/dev/null | tail -n 1 | tr -d '\r\n')"
[[ -n "$KEY" && "$KEY" != *[[:space:]]* ]] || {
  echo "headscale did not return a valid preauth key" >&2
  exit 5
}

python3 - "$KEY" <<'PY'
import json
import sys
print(json.dumps({"auth_key": sys.argv[1]}, separators=(",", ":")))
PY
