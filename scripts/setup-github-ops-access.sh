#!/usr/bin/env bash
set -Eeuo pipefail

REPO="Bakunity/RDP"
DEPLOY_USER="bakunity-deploy"
ROOT_HELPER="/usr/local/sbin/bakunity-rdp-github-ops"
DISPATCHER="/usr/local/bin/bakunity-rdp-github-dispatch"
SUDOERS="/etc/sudoers.d/bakunity-rdp-github-ops"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through sudo." >&2
  exit 1
fi

public_key="${1:-}"
if ! [[ "${public_key}" =~ ^ssh-ed25519[[:space:]][A-Za-z0-9+/=]+([[:space:]].*)?$ ]]; then
  echo "Pass one ssh-ed25519 public key as the first argument." >&2
  exit 64
fi

if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
  useradd     --system     --create-home     --home-dir "/var/lib/${DEPLOY_USER}"     --shell /bin/bash     "${DEPLOY_USER}"
fi

install -o root -g root -m 0755   "/opt/hermes-rdp/source/server/bin/bakunity-rdp-github-ops.sh"   "${ROOT_HELPER}"

cat > "${DISPATCHER}" <<'EOF'
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
esac

echo "Command denied." >&2
exit 64
EOF
chmod 0755 "${DISPATCHER}"
chown root:root "${DISPATCHER}"

cat > "${SUDOERS}" <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: ${ROOT_HELPER}
EOF
chmod 0440 "${SUDOERS}"
visudo -cf "${SUDOERS}" >/dev/null

home="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 0700 "${home}/.ssh"
authorized="${home}/.ssh/authorized_keys"
printf '%s %s\n'   'no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty,no-user-rc,command="/usr/local/bin/bakunity-rdp-github-dispatch"'   "${public_key}" > "${authorized}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${authorized}"
chmod 0600 "${authorized}"

echo "GITHUB_OPS_ACCESS=PASS"
echo "DEPLOY_USER=${DEPLOY_USER}"
echo "ALLOWED_COMMANDS=doctor,deploy-main"
