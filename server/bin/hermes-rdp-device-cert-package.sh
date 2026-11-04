#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIG=/etc/hermes-rdp/config.json
CERTBOT=/usr/local/bin/certbot
MODE="package"
DEVICE_ID=""

usage() {
  echo "usage: hermes-rdp-device-cert-package [--status|--package] DEVICE_ID" >&2
}

while (($#)); do
  case "$1" in
    --status) MODE="status"; shift ;;
    --package) MODE="package"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [[ -z "$DEVICE_ID" ]]; then
        DEVICE_ID="$1"
        shift
      else
        usage
        exit 2
      fi
      ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "Bakunity device certificate helper must run as root" >&2
  exit 1
fi
if ! [[ "$DEVICE_ID" =~ ^[0-9a-fA-F]{32}$ ]]; then
  echo "invalid device id" >&2
  exit 2
fi
if [[ ! -s "$CONFIG" ]]; then
  echo "missing Bakunity RDP config" >&2
  exit 1
fi
for command in openssl python3 base64 flock curl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "missing required command: $command" >&2
    exit 1
  }
done
if [[ ! -x "$CERTBOT" ]]; then
  echo "certbot is unavailable" >&2
  exit 1
fi

readarray -t INFO < <(
  python3 - "$DEVICE_ID" <<'PY'
import json
import re
import sqlite3
import sys
from pathlib import Path

device_id = sys.argv[1]
config = json.loads(Path("/etc/hermes-rdp/config.json").read_text(encoding="utf-8"))
trusted = config.get("trusted_rdp_certificate") or {}
if trusted.get("enabled") is not True:
    raise SystemExit("trusted RDP certificate lifecycle is disabled")

db_path = str(config.get("db_path") or "/var/lib/hermes-rdp/state.sqlite3")
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
try:
    device = conn.execute(
        "SELECT id,slug FROM devices WHERE id=? AND revoked=0",
        (device_id,),
    ).fetchone()
    domain_row = conn.execute(
        "SELECT value FROM settings WHERE key='device_domain'"
    ).fetchone()
finally:
    conn.close()

if not device:
    raise SystemExit("device not found")
slug = str(device["slug"] or "").strip().lower()
domain = str(domain_row["value"] if domain_row else "").strip().lower().rstrip(".")
if not slug or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", slug):
    raise SystemExit("device slug is invalid")
if (
    not domain
    or len(domain) > 253
    or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in domain.split(".")
    )
):
    raise SystemExit("device domain is invalid")

host = f"{slug}.{domain}"
cert_name = f"bakunity-rdp-device-{device_id}"
acme_mode = str(trusted.get("acme_mode") or "standalone")
webroot = str(trusted.get("acme_webroot") or "/var/www/hermes-rdp-acme")
print(host)
print(domain)
print(cert_name)
print(acme_mode)
print(webroot)
PY
)

if ((${#INFO[@]} != 5)); then
  echo "invalid device certificate configuration" >&2
  exit 1
fi

HOST="${INFO[0]}"
DOMAIN="${INFO[1]}"
CERT_NAME="${INFO[2]}"
ACME_MODE="${INFO[3]}"
ACME_WEBROOT="${INFO[4]}"
LIVE="/etc/letsencrypt/live/$CERT_NAME"
RENEW="/etc/letsencrypt/renewal/$CERT_NAME.conf"
LOCK="/run/hermes-rdp-device-cert-$DEVICE_ID.lock"

exec 9>"$LOCK"
if ! flock -w 90 9; then
  echo "timed out waiting for device certificate lock" >&2
  exit 1
fi

port80_listener() {
  ss -H -ltnp '( sport = :80 )' 2>/dev/null || true
}

configure_nginx_route() {
  command -v nginx >/dev/null 2>&1 || {
    echo "nginx webroot mode is configured but nginx is unavailable" >&2
    return 1
  }
  systemctl is-active --quiet nginx || {
    echo "nginx webroot mode is configured but nginx is not active" >&2
    return 1
  }

  local target=""
  if grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/conf\.d/\*\.conf;' /etc/nginx/nginx.conf 2>/dev/null; then
    target=/etc/nginx/conf.d/hermes-rdp-device-acme.conf
  elif grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/sites-enabled/\*;' /etc/nginx/nginx.conf 2>/dev/null; then
    target=/etc/nginx/sites-enabled/hermes-rdp-device-acme.conf
  else
    echo "no supported nginx include path for Bakunity ACME route" >&2
    return 1
  fi

  if [[ -e "$target" ]] && ! grep -q '^# Managed by Bakunity RDP device certificates$' "$target"; then
    echo "refusing to overwrite unmanaged nginx config: $target" >&2
    return 1
  fi

  install -d -m 0755 "$ACME_WEBROOT/.well-known/acme-challenge"
  local temp
  temp="$(mktemp)"
  cat >"$temp" <<EOF
# Managed by Bakunity RDP device certificates
server {
    listen 80;
    listen [::]:80;
    server_name *.$DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        alias $ACME_WEBROOT/.well-known/acme-challenge/;
        default_type text/plain;
    }

    location / {
        return 404;
    }
}
EOF
  if [[ ! -e "$target" ]] || ! cmp -s "$temp" "$target"; then
    install -m 0644 "$temp" "$target"
    nginx -t >/dev/null
    systemctl reload nginx
  fi
  rm -f "$temp"

  local probe body=""
  probe="bakunity-$(openssl rand -hex 8)"
  printf '%s\n' "$probe" >"$ACME_WEBROOT/.well-known/acme-challenge/$probe"
  for _ in {1..20}; do
    body="$(curl -fsS --max-time 2 -H "Host: $HOST" "http://127.0.0.1/.well-known/acme-challenge/$probe" 2>/dev/null || true)"
    [[ "$body" == "$probe" ]] && break
    sleep 0.25
  done
  rm -f "$ACME_WEBROOT/.well-known/acme-challenge/$probe"
  [[ "$body" == "$probe" ]] || {
    echo "Bakunity device ACME nginx route readiness probe failed" >&2
    return 1
  }
}

certificate_is_usable() {
  [[ -s "$LIVE/cert.pem" && -s "$LIVE/chain.pem" && -s "$LIVE/privkey.pem" ]] || return 1
  openssl x509 -in "$LIVE/cert.pem" -noout -checkhost "$HOST" >/dev/null 2>&1 || return 1
  openssl x509 -in "$LIVE/cert.pem" -noout -checkend 604800 >/dev/null 2>&1 || return 1
  openssl verify     -CApath /etc/ssl/certs     -untrusted "$LIVE/chain.pem"     "$LIVE/cert.pem" >/dev/null 2>&1 || return 1
  return 0
}

ensure_certificate() {
  certificate_is_usable && return 0

  local -a auth_args=()
  if [[ "$ACME_MODE" == "nginx-webroot" ]]; then
    configure_nginx_route
    auth_args=(--webroot --webroot-path "$ACME_WEBROOT")
  else
    if [[ -n "$(port80_listener)" ]]; then
      echo "TCP 80 is occupied; standalone HTTP-01 cannot start" >&2
      return 1
    fi
    auth_args=(--standalone)
  fi

  local -a behavior=()
  if [[ -e "$RENEW" ]]; then
    behavior=(--renew-with-new-domains)
  fi

  "$CERTBOT" certonly     "${auth_args[@]}"     "${behavior[@]}"     --preferred-challenges http     --cert-name "$CERT_NAME"     --domain "$HOST"     --key-type rsa     --rsa-key-size 2048     --non-interactive     --agree-tos     --register-unsafely-without-email

  certificate_is_usable || {
    echo "issued certificate failed validation for $HOST" >&2
    return 1
  }
}

ensure_certificate

CERT="$LIVE/cert.pem"
CHAIN="$LIVE/chain.pem"
KEY="$LIVE/privkey.pem"

THUMBPRINT="$(
  openssl x509 -in "$CERT" -noout -fingerprint -sha1 |
    cut -d= -f2 |
    tr -d ':' |
    tr '[:lower:]' '[:upper:]'
)"
SHA256="$(
  openssl x509 -in "$CERT" -noout -fingerprint -sha256 |
    cut -d= -f2 |
    tr -d ':' |
    tr '[:lower:]' '[:upper:]'
)"
NOT_AFTER="$(openssl x509 -in "$CERT" -noout -enddate | cut -d= -f2-)"

if [[ "$MODE" == "status" ]]; then
  python3 - "$HOST" "$THUMBPRINT" "$SHA256" "$NOT_AFTER" <<'PY'
import json
import sys
import time

host, thumbprint, sha256, not_after = sys.argv[1:]
print(json.dumps({
    "enabled": True,
    "cert_name": host,
    "thumbprint": thumbprint,
    "sha256": sha256,
    "not_after": not_after,
    "generated_at": int(time.time()),
}, separators=(",", ":")))
PY
  exit 0
fi

WORK="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT

PASSWORD="$(openssl rand -hex 24)"
export HERMES_PFX_PASSWORD="$PASSWORD"
PFX="$WORK/bakunity-rdp-device.pfx"

openssl pkcs12 -export   -out "$PFX"   -inkey "$KEY"   -in "$CERT"   -certfile "$CHAIN"   -name "Bakunity RDP $HOST"   -passout env:HERMES_PFX_PASSWORD   >/dev/null 2>&1

PFX_BASE64="$(base64 -w 0 "$PFX")"

python3 - "$HOST" "$THUMBPRINT" "$SHA256" "$NOT_AFTER" "$PASSWORD" "$PFX_BASE64" <<'PY'
import json
import sys

host, thumbprint, sha256, not_after, password, pfx_base64 = sys.argv[1:]
print(json.dumps({
    "cert_name": host,
    "thumbprint": thumbprint,
    "sha256": sha256,
    "not_after": not_after,
    "password": password,
    "pfx_base64": pfx_base64,
}, separators=(",", ":")))
PY
