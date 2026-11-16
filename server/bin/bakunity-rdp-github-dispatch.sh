#!/usr/bin/env bash
set -Eeuo pipefail

original="${SSH_ORIGINAL_COMMAND:-}"
case "${original}" in
  doctor)
    exec sudo -n /usr/local/sbin/bakunity-rdp-github-ops doctor
    ;;
  deploy\ *)
    sha="${original#deploy }"
    if [[ "${sha}" =~ ^[0-9a-fA-F]{40}$ ]]; then
      exec sudo -n /usr/local/sbin/bakunity-rdp-github-ops deploy "${sha}"
    fi
    ;;
  restart\ *)
    target="${original#restart }"
    if [[ "${target}" =~ ^[a-z0-9-]{1,48}$ ]]; then
      exec sudo -n /usr/local/sbin/bakunity-rdp-github-ops restart "${target}"
    fi
    ;;
esac

echo "Command denied." >&2
exit 64
