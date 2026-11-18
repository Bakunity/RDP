#!/usr/bin/env bash
set -Eeuo pipefail

if (($# != 1)) || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  echo "usage: hermes-rdp-close-tunnel PORT" >&2
  exit 2
fi
PORT="$1"

read -r START END < <(
  python3 - <<'PY'
import json
with open("/etc/hermes-rdp/config.json", encoding="utf-8") as handle:
    data = json.load(handle)
print(int(data["port_start"]), int(data["port_end"]))
PY
)

ACCESS_START=$((START + 1000))
ACCESS_END=$((END + 1000))
if ! (
  ((PORT >= START && PORT <= END)) ||
  ((PORT >= ACCESS_START && PORT <= ACCESS_END))
); then
  echo "port outside Bakunity device tunnel ranges" >&2
  exit 2
fi

CLOSED=0
while read -r PID; do
  [[ -n "$PID" && -e "/proc/$PID/exe" ]] || continue
  EXE="$(readlink -f "/proc/$PID/exe" 2>/dev/null || true)"
  if [[ "$EXE" == /usr/sbin/sshd ]]; then
    kill -TERM "$PID"
    CLOSED=1
  fi
done < <(
  ss -H -ltnp "sport = :$PORT" 2>/dev/null |
    grep -oE 'pid=[0-9]+' |
    cut -d= -f2 |
    sort -u
)

if ((CLOSED == 0)); then
  exit 3
fi
