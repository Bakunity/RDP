#!/usr/bin/env bash
set -Eeuo pipefail

MARKER="/etc/hermes-rdp/autodeploy.enabled"
TIMER="hermes-rdp-autodeploy.timer"
SERVICE="hermes-rdp-autodeploy.service"

[[ ${EUID} -eq 0 ]] || {
  echo "Must run as root." >&2
  exit 77
}
[[ $# -eq 1 ]] || {
  echo "usage: hermes-rdp-autodeploy-control on|off" >&2
  exit 64
}

case "$1" in
  on)
    touch "$MARKER"
    chmod 0644 "$MARKER"
    systemctl enable --now "$TIMER" >/dev/null
    systemctl start --no-block "$SERVICE" >/dev/null 2>&1 || true
    echo "AUTODEPLOY=ON"
    ;;
  off)
    rm -f "$MARKER"
    systemctl disable --now "$TIMER" >/dev/null 2>&1 || true
    echo "AUTODEPLOY=OFF"
    ;;
  *)
    echo "usage: hermes-rdp-autodeploy-control on|off" >&2
    exit 64
    ;;
esac
