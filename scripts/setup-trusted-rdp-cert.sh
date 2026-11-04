#!/usr/bin/env bash
set -Eeuo pipefail

CERTBOT_VERSION="${HERMES_CERTBOT_VERSION:-5.7.0}"
HOST=""

usage() {
  cat <<'EOF'
Usage:
  setup-trusted-rdp-cert.sh --host PUBLIC_IPV4

Installs and configures the Hermes RDP trusted public-IP certificate lifecycle:
- Certbot in /opt/certbot;
- UFW TCP 80 rule for ACME HTTP-01;
- automatic ACME mode: standalone when TCP 80 is free, nginx webroot when nginx owns TCP 80;
- isolated Let's Encrypt staging validation before first production issuance;
- production short-lived IP certificate;
- Hermes-owned systemd renewal service/timer;
- bounded root helper for authenticated Windows certificate delivery;
- non-secret certificate state for automatic Windows rotation checks.
EOF
}

while (($#)); do
  case "$1" in
    --host) HOST="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root or through sudo." >&2
  exit 1
fi
if [[ -z "$HOST" ]]; then
  usage >&2
  exit 2
fi

python3 - "$HOST" <<'PY'
import ipaddress
import sys

value = ipaddress.ip_address(sys.argv[1])
if value.version != 4 or not value.is_global:
    raise SystemExit('trusted RDP certificate requires a globally routable public IPv4 address')
PY

CONFIG=/etc/hermes-rdp/config.json
LIVE="/etc/letsencrypt/live/$HOST"
RENEW="/etc/letsencrypt/renewal/$HOST.conf"
MARKER=/etc/hermes-rdp/trusted-rdp-cert.enabled
STATE=/etc/hermes-rdp/trusted-rdp-cert-state.json
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CERT_RENEW_SOURCE="$SOURCE_ROOT/server/bin/hermes-rdp-cert-renew.sh"
CERT_STATE_SOURCE="$SOURCE_ROOT/server/bin/hermes-rdp-cert-state-refresh.sh"
CERT_PACKAGE_SOURCE="$SOURCE_ROOT/server/bin/hermes-rdp-cert-package.sh"
CERT_PACKAGE_SUDOERS_SOURCE="$SOURCE_ROOT/server/sudoers/hermes-rdp-cert-package"
SERVICE_SOURCE="$SOURCE_ROOT/server/systemd/hermes-rdp-cert-renew.service"
TIMER_SOURCE="$SOURCE_ROOT/server/systemd/hermes-rdp-cert-renew.timer"
ACME_MODE="standalone"
ACME_WEBROOT=/var/www/hermes-rdp-acme
NGINX_CONF=""
NGINX_CONF_CHANGED=0
NGINX_CONF_PREEXISTED=0
SETUP_COMPLETE=0
WORK="$(mktemp -d)"
STAGE_ROOT=""

cleanup() {
  local status=$?
  if ((status != 0 && SETUP_COMPLETE == 0 && NGINX_CONF_CHANGED == 1)); then
    if ((NGINX_CONF_PREEXISTED == 1)); then
      cp -a "$WORK/nginx-conf.backup" "$NGINX_CONF" || true
    else
      rm -f "$NGINX_CONF" || true
    fi
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
      systemctl reload nginx >/dev/null 2>&1 || true
    fi
  fi
  [[ -n "$STAGE_ROOT" ]] && rm -rf "$STAGE_ROOT"
  rm -rf "$WORK"
}
trap cleanup EXIT

for required in \
  "$CONFIG" \
  "$CERT_RENEW_SOURCE" \
  "$CERT_STATE_SOURCE" \
  "$CERT_PACKAGE_SOURCE" \
  "$CERT_PACKAGE_SUDOERS_SOURCE" \
  "$SERVICE_SOURCE" \
  "$TIMER_SOURCE"; do
  if [[ ! -e "$required" ]]; then
    echo "Missing required Hermes file: $required" >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates \
  curl \
  openssl \
  python3 \
  python3-venv \
  sudo \
  ufw \
  util-linux >/dev/null

install_certbot() {
  local install_required=1 existing_version=""

  if [[ -x /opt/certbot/bin/certbot ]]; then
    existing_version="$(/opt/certbot/bin/certbot --version 2>/dev/null | awk '{print $2}' || true)"
    if python3 - "$existing_version" "$CERTBOT_VERSION" <<'PY'
import re
import sys

def version_tuple(value: str):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', value or '')
    if not match:
        raise SystemExit(1)
    return tuple(int(part) for part in match.groups())

raise SystemExit(0 if version_tuple(sys.argv[1]) >= version_tuple(sys.argv[2]) else 1)
PY
    then
      install_required=0
    fi
  fi

  if ((install_required == 1)); then
    rm -rf /opt/certbot
    python3 -m venv /opt/certbot
    /opt/certbot/bin/pip install \
      --disable-pip-version-check \
      --quiet \
      "certbot==$CERTBOT_VERSION"
  fi

  ln -sfn /opt/certbot/bin/certbot /usr/local/bin/certbot
  /usr/local/bin/certbot --version
}

port80_listener() {
  ss -H -ltnp '( sport = :80 )' 2>/dev/null || true
}

configure_nginx_webroot() {
  command -v nginx >/dev/null 2>&1 || {
    echo "TCP 80 is occupied by a process that looks like nginx, but nginx CLI is unavailable." >&2
    return 1
  }
  systemctl is-active --quiet nginx || {
    echo "TCP 80 is occupied by nginx, but nginx.service is not active." >&2
    return 1
  }

  if grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/conf\.d/\*\.conf;' /etc/nginx/nginx.conf 2>/dev/null; then
    NGINX_CONF=/etc/nginx/conf.d/hermes-rdp-acme.conf
  elif grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/sites-enabled/\*;' /etc/nginx/nginx.conf 2>/dev/null; then
    NGINX_CONF=/etc/nginx/sites-enabled/hermes-rdp-acme.conf
  else
    echo "nginx owns TCP 80, but no supported conf.d/sites-enabled include was found." >&2
    return 1
  fi

  if [[ -e "$NGINX_CONF" ]]; then
    if ! grep -q '^# Managed by Hermes RDP$' "$NGINX_CONF"; then
      echo "Refusing to overwrite unmanaged nginx config: $NGINX_CONF" >&2
      return 1
    fi
    cp -a "$NGINX_CONF" "$WORK/nginx-conf.backup"
    NGINX_CONF_PREEXISTED=1
  fi

  install -d -m 0755 "$ACME_WEBROOT/.well-known/acme-challenge"
  cat >"$WORK/hermes-rdp-acme.conf" <<EOF
# Managed by Hermes RDP
server {
    listen 80;
    listen [::]:80;
    server_name $HOST;

    location ^~ /.well-known/acme-challenge/ {
        alias $ACME_WEBROOT/.well-known/acme-challenge/;
        default_type text/plain;
    }

    location / {
        return 404;
    }
}
EOF
  install -m 0644 "$WORK/hermes-rdp-acme.conf" "$NGINX_CONF"
  NGINX_CONF_CHANGED=1

  nginx -t
  systemctl reload nginx

  local probe body attempt
  probe="hermes-$(openssl rand -hex 12)"
  printf '%s\n' "$probe" >"$ACME_WEBROOT/.well-known/acme-challenge/$probe"
  body=""
  for attempt in {1..20}; do
    body="$(curl -fsS --max-time 2 -H "Host: $HOST" "http://127.0.0.1/.well-known/acme-challenge/$probe" 2>/dev/null || true)"
    if [[ "$body" == "$probe" ]]; then
      break
    fi
    sleep 0.25
  done
  rm -f "$ACME_WEBROOT/.well-known/acme-challenge/$probe"
  [[ "$body" == "$probe" ]] || {
    echo "nginx ACME webroot readiness probe failed after bounded retries." >&2
    return 1
  }

  ACME_MODE="nginx-webroot"
  return 0
}

select_acme_mode() {
  local listeners
  listeners="$(port80_listener)"
  if [[ -z "$listeners" ]]; then
    ACME_MODE="standalone"
    return 0
  fi
  if grep -q 'nginx' <<<"$listeners"; then
    configure_nginx_webroot
    return
  fi
  echo "TCP 80 is already occupied by a non-nginx service; automatic HTTP-01 cannot take over the port." >&2
  printf '%s\n' "$listeners" >&2
  return 1
}

certbot_auth_args() {
  if [[ "$ACME_MODE" == "nginx-webroot" ]]; then
    printf '%s\n' --webroot --webroot-path "$ACME_WEBROOT"
  else
    printf '%s\n' --standalone
  fi
}

install_certbot
select_acme_mode
ufw allow 80/tcp comment 'Hermes ACME HTTP-01' >/dev/null || true

certificate_is_usable() {
  [[ -s "$LIVE/cert.pem" && -s "$LIVE/chain.pem" && -s "$LIVE/fullchain.pem" && -s "$LIVE/privkey.pem" ]] || return 1
  openssl x509 -in "$LIVE/cert.pem" -noout -checkip "$HOST" >/dev/null 2>&1 || return 1
  if openssl x509 -in "$LIVE/cert.pem" -noout -issuer | grep -q '(STAGING)'; then
    return 1
  fi
  openssl verify \
    -CApath /etc/ssl/certs \
    -untrusted "$LIVE/chain.pem" \
    "$LIVE/cert.pem" >/dev/null 2>&1 || return 1
  return 0
}

mapfile -t AUTH_ARGS < <(certbot_auth_args)

if ! certificate_is_usable; then
  if [[ -e "$LIVE" || -e "$RENEW" ]]; then
    echo "Existing certificate lineage for $HOST is present but is not usable." >&2
    echo "Refusing to delete or overwrite it automatically." >&2
    exit 1
  fi

  STAGE_ROOT="$(mktemp -d)"
  mkdir -p "$STAGE_ROOT/config" "$STAGE_ROOT/work" "$STAGE_ROOT/logs"

  /usr/local/bin/certbot certonly \
    --staging \
    --preferred-profile shortlived \
    "${AUTH_ARGS[@]}" \
    --ip-address "$HOST" \
    --cert-name "$HOST" \
    --key-type rsa \
    --rsa-key-size 2048 \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email \
    --config-dir "$STAGE_ROOT/config" \
    --work-dir "$STAGE_ROOT/work" \
    --logs-dir "$STAGE_ROOT/logs"

  rm -rf "$STAGE_ROOT"
  STAGE_ROOT=""

  if [[ "$ACME_MODE" == "standalone" ]] && [[ -n "$(port80_listener)" ]]; then
    echo "TCP 80 remained occupied after standalone staging validation." >&2
    exit 1
  fi

  /usr/local/bin/certbot certonly \
    --preferred-profile shortlived \
    "${AUTH_ARGS[@]}" \
    --ip-address "$HOST" \
    --cert-name "$HOST" \
    --key-type rsa \
    --rsa-key-size 2048 \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email
fi

if ! certificate_is_usable; then
  echo "Production certificate validation failed after issuance." >&2
  exit 1
fi

CERT_PUB="$(
  openssl x509 -in "$LIVE/cert.pem" -pubkey -noout |
    openssl pkey -pubin -outform DER 2>/dev/null |
    sha256sum |
    awk '{print $1}'
)"
KEY_PUB="$(
  openssl pkey -in "$LIVE/privkey.pem" -pubout 2>/dev/null |
    openssl pkey -pubin -outform DER 2>/dev/null |
    sha256sum |
    awk '{print $1}'
)"
if [[ "$CERT_PUB" != "$KEY_PUB" ]]; then
  echo "Production certificate/private-key mismatch." >&2
  exit 1
fi
unset CERT_PUB KEY_PUB

install -m 0755 "$CERT_RENEW_SOURCE" /usr/local/sbin/hermes-rdp-cert-renew
install -m 0755 "$CERT_STATE_SOURCE" /usr/local/sbin/hermes-rdp-cert-state-refresh
install -m 0755 "$CERT_PACKAGE_SOURCE" /usr/local/sbin/hermes-rdp-cert-package
install -m 0440 \
  "$CERT_PACKAGE_SUDOERS_SOURCE" \
  /etc/sudoers.d/hermes-rdp-cert-package
visudo -cf /etc/sudoers.d/hermes-rdp-cert-package >/dev/null
install -m 0644 "$SERVICE_SOURCE" /etc/systemd/system/hermes-rdp-cert-renew.service
install -m 0644 "$TIMER_SOURCE" /etc/systemd/system/hermes-rdp-cert-renew.timer

python3 - "$CONFIG" "$HOST" "$STATE" "$ACME_MODE" "$ACME_WEBROOT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
host = sys.argv[2]
state_file = sys.argv[3]
acme_mode = sys.argv[4]
acme_webroot = sys.argv[5]
data = json.loads(path.read_text(encoding='utf-8'))
data['trusted_rdp_certificate'] = {
    'enabled': True,
    'cert_name': host,
    'live_dir': f'/etc/letsencrypt/live/{host}',
    'profile': 'shortlived',
    'renewal_timer': 'hermes-rdp-cert-renew.timer',
    'state_file': state_file,
    'acme_mode': acme_mode,
}
if acme_mode == 'nginx-webroot':
    data['trusted_rdp_certificate']['acme_webroot'] = acme_webroot
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
chmod 0640 "$CONFIG"
chown root:hermes-rdp "$CONFIG"
printf '%s\n' "$HOST" > "$MARKER"
chmod 0644 "$MARKER"

/usr/local/sbin/hermes-rdp-cert-state-refresh >/dev/null
if [[ ! -s "$STATE" ]]; then
  echo "Hermes certificate state file was not created." >&2
  exit 1
fi

systemd-analyze verify \
  /etc/systemd/system/hermes-rdp-cert-renew.service \
  /etc/systemd/system/hermes-rdp-cert-renew.timer
systemctl daemon-reload
systemctl enable --now hermes-rdp-cert-renew.timer

SERIAL_BEFORE="$(openssl x509 -in "$LIVE/cert.pem" -noout -serial | cut -d= -f2)"
systemctl start hermes-rdp-cert-renew.service
if [[ "$(systemctl show hermes-rdp-cert-renew.service -p Result --value)" != "success" ]]; then
  echo "Hermes certificate renewal service smoke test failed." >&2
  exit 1
fi
SERIAL_AFTER="$(openssl x509 -in "$LIVE/cert.pem" -noout -serial | cut -d= -f2)"

if [[ "$ACME_MODE" == "standalone" ]]; then
  if [[ -n "$(port80_listener)" ]]; then
    echo "TCP 80 remained occupied after standalone renewal smoke test." >&2
    exit 1
  fi
else
  systemctl is-active --quiet nginx || {
    echo "nginx is not active after renewal smoke test." >&2
    exit 1
  }
  nginx -t >/dev/null
fi

SETUP_COMPLETE=1
printf '\n=== HERMES TRUSTED RDP CERTIFICATE ===\n'
echo "certificate=$LIVE/fullchain.pem"
echo "private_key=$LIVE/privkey.pem"
echo "renewal_timer=$(systemctl is-active hermes-rdp-cert-renew.timer)"
echo "renewal_enabled=$(systemctl is-enabled hermes-rdp-cert-renew.timer)"
if [[ "$SERIAL_BEFORE" == "$SERIAL_AFTER" ]]; then
  echo "renewal_smoke=PASS_NOT_DUE"
else
  echo "renewal_smoke=PASS_RENEWED"
fi
echo "acme_mode=$ACME_MODE"
if [[ "$ACME_MODE" == "standalone" ]]; then
  echo "tcp80=FREE"
else
  echo "tcp80=NGINX_WEBROOT"
fi
echo "package_helper=READY"
echo "certificate_state=READY"
echo "TRUSTED_RDP_CERT=PASS"
