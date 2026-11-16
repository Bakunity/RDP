#!/usr/bin/env bash
set -Eeuo pipefail

REPO="Bakunity/RDP"
CTL="/usr/local/bin/bakunity-rdpctl"

usage() {
  echo "usage: bakunity-rdp-github-ops doctor | deploy <40-char-main-sha> | restart <device-slug> | on <device-slug> | off <device-slug>" >&2
  exit 64
}

[[ ${EUID} -eq 0 ]] || {
  echo "Must run as root." >&2
  exit 77
}

action="${1:-}"
case "${action}" in
  doctor)
    [[ $# -eq 1 ]] || usage
    echo "=== BAKUNITY RDP PRODUCTION DOCTOR ==="
    exec "${CTL}" doctor
    ;;
  deploy)
    [[ $# -eq 2 ]] || usage
    sha="${2,,}"
    [[ "${sha}" =~ ^[0-9a-f]{40}$ ]] || usage

    main_sha="$(
      curl -fsSL         -H 'Accept: application/vnd.github+json'         "https://api.github.com/repos/${REPO}/commits/main" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"].lower())'
    )"
    [[ "${main_sha}" =~ ^[0-9a-f]{40}$ ]] || {
      echo "Unable to resolve trusted main SHA." >&2
      exit 69
    }
    if [[ "${sha}" != "${main_sha}" ]]; then
      echo "DEPLOY=DENIED requested=${sha} main=${main_sha}" >&2
      exit 65
    fi

    tmp="$(mktemp)"
    trap 'rm -f "${tmp}"' EXIT
    curl -fsSL       "https://raw.githubusercontent.com/${REPO}/${sha}/scripts/update-server.sh"       -o "${tmp}"
    chmod 0700 "${tmp}"

    echo "=== BAKUNITY RDP PRODUCTION DEPLOY ==="
    echo "DEPLOY_SHA=${sha}"
    env BAKUNITY_RDP_REF="${sha}" bash "${tmp}"
    echo
    echo "=== POST-DEPLOY DOCTOR ==="
    "${CTL}" doctor
    echo "PRODUCTION_DEPLOY=PASS"
    ;;
  restart)
    [[ $# -eq 2 ]] || usage
    target="${2,,}"
    [[ "${target}" =~ ^[a-z0-9-]{1,48}$ ]] || usage
    echo "=== BAKUNITY RDP DEVICE RESTART ==="
    exec "${CTL}" devices restart "${target}"
    ;;
  on|off)
    [[ $# -eq 2 ]] || usage
    target="${2,,}"
    [[ "${target}" =~ ^[a-z0-9-]{1,48}$ ]] || usage
    echo "=== BAKUNITY RDP DEVICE ACCESS ==="
    exec "${CTL}" devices access "${target}" "${action}"
    ;;
  *)
    usage
    ;;
esac
