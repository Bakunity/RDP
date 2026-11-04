#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through sudo." >&2
  exit 1
fi

read -r -p "Type REMOVE to uninstall Hermes RDP server: " ANSWER
[[ "$ANSWER" == "REMOVE" ]] || exit 1

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/hermes-rdp/uninstall-$STAMP"
install -d -m 0700 "$BACKUP"

for path in \
  /etc/hermes-rdp \
  /opt/hermes-rdp \
  /var/lib/hermes-rdp \
  /etc/systemd/system/hermes-rdp.service \
  /etc/systemd/system/hermes-rdp-sshd.service \
  /etc/systemd/system/hermes-rdp-cert-renew.service \
  /etc/systemd/system/hermes-rdp-cert-renew.timer \
  /usr/local/sbin/hermes-rdp-cert-renew \
  /usr/local/sbin/hermes-rdp-cert-state-refresh \
  /usr/local/sbin/hermes-rdp-cert-package \
  /etc/sudoers.d/hermes-rdp \
  /etc/sudoers.d/hermes-rdp-cert-package \
  /etc/nginx/conf.d/hermes-rdp-acme.conf \
  /etc/nginx/sites-enabled/hermes-rdp-acme.conf; do
  [[ -e "$path" ]] && cp -a --parents "$path" "$BACKUP/"
done

systemctl disable --now \
  hermes-rdp-cert-renew.timer \
  hermes-rdp.service \
  hermes-rdp-sshd.service 2>/dev/null || true

rm -f \
  /etc/systemd/system/hermes-rdp.service \
  /etc/systemd/system/hermes-rdp-sshd.service \
  /etc/systemd/system/hermes-rdp-cert-renew.service \
  /etc/systemd/system/hermes-rdp-cert-renew.timer \
  /etc/hermes-rdp/trusted-rdp-cert.enabled \
  /etc/sudoers.d/hermes-rdp \
  /etc/sudoers.d/hermes-rdp-cert-package \
  /usr/local/bin/hermes-rdpctl \
  /usr/local/bin/hermes-rdp-authorized-keys \
  /usr/local/sbin/hermes-rdp-close-tunnel \
  /usr/local/sbin/hermes-rdp-cert-renew \
  /usr/local/sbin/hermes-rdp-cert-state-refresh \
  /usr/local/sbin/hermes-rdp-cert-package

NGINX_CHANGED=0
for nginx_conf in \
  /etc/nginx/conf.d/hermes-rdp-acme.conf \
  /etc/nginx/sites-enabled/hermes-rdp-acme.conf; do
  if [[ -f "$nginx_conf" ]] && grep -q '^# Managed by Hermes RDP$' "$nginx_conf"; then
    rm -f "$nginx_conf"
    NGINX_CHANGED=1
  fi
done
if ((NGINX_CHANGED == 1)) && command -v nginx >/dev/null 2>&1; then
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx >/dev/null 2>&1 || true
  else
    echo "Warning: nginx configuration is invalid after Hermes ACME route removal; nginx was not reloaded." >&2
  fi
fi

systemctl daemon-reload

echo "Hermes RDP services removed."
echo "Data, configuration and ACME certificate lineage were preserved."
echo "Backup: $BACKUP"
