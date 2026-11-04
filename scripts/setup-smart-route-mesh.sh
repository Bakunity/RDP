#!/usr/bin/env bash
set -Eeuo pipefail

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
HEADSCALE_VERSION="${BAKUNITY_HEADSCALE_VERSION:-0.29.7}"
CERTBOT_VERSION="${HERMES_CERTBOT_VERSION:-5.7.0}"
CONFIG=/etc/hermes-rdp/config.json
DB=/var/lib/hermes-rdp/state.sqlite3
HEADSCALE_CONFIG=/etc/headscale/config.yaml
HEADSCALE_POLICY=/etc/headscale/policy.hujson
MESH_MARKER=/etc/hermes-rdp/smart-route-mesh.enabled
MESH_KEY_HELPER=/usr/local/sbin/bakunity-rdp-mesh-key
MESH_SUDOERS=/etc/sudoers.d/bakunity-rdp-mesh-key
ACME_WEBROOT=/var/www/hermes-rdp-acme
CERT_NAME=bakunity-rdp-mesh
RENEW_HOOK=/etc/letsencrypt/renewal-hooks/deploy/bakunity-rdp-mesh-nginx
WORK="$(mktemp -d)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/hermes-rdp/smart-route-mesh-$STAMP"
NGINX_CONF=""
ROLLBACK_ARMED=0
HEADSCALE_SERVICE_EXISTED=0
HEADSCALE_WAS_ENABLED=0
HEADSCALE_WAS_ACTIVE=0

if systemctl cat headscale.service >/dev/null 2>&1; then
  HEADSCALE_SERVICE_EXISTED=1
  systemctl is-enabled --quiet headscale.service && HEADSCALE_WAS_ENABLED=1 || true
  systemctl is-active --quiet headscale.service && HEADSCALE_WAS_ACTIVE=1 || true
fi

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

restore_optional() {
  local path="$1"
  rm -f "$path"
  if [[ -e "$BACKUP$path" ]]; then
    install -d -m 0755 "$(dirname "$path")"
    cp -a "$BACKUP$path" "$path"
  fi
}

rollback_setup() {
  local status="$1" line="$2"
  trap - ERR
  set +e
  if ((ROLLBACK_ARMED == 1)); then
    echo "Smart Route mesh setup failed at line $line; restoring $BACKUP" >&2
    restore_optional "$HEADSCALE_CONFIG"
    restore_optional "$HEADSCALE_POLICY"
    restore_optional "$MESH_MARKER"
    restore_optional "$MESH_KEY_HELPER"
    restore_optional "$MESH_SUDOERS"
    restore_optional "$RENEW_HOOK"
    if [[ -n "$NGINX_CONF" ]]; then restore_optional "$NGINX_CONF"; fi
    if [[ -s "$BACKUP/settings.json" ]]; then
      python3 - "$DB" "$BACKUP/settings.json" <<'PY'
import json
import sqlite3
import sys

db_path, settings_path = sys.argv[1:]
values = json.load(open(settings_path, encoding="utf-8"))
with sqlite3.connect(db_path) as conn:
    for key in ("smart_route_enabled", "smart_route_control_url"):
        value = values.get(key)
        if value is None:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
PY
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl stop headscale.service >/dev/null 2>&1 || true
    if ((HEADSCALE_SERVICE_EXISTED == 1)); then
      if ((HEADSCALE_WAS_ENABLED == 1)); then
        systemctl enable headscale.service >/dev/null 2>&1 || true
      else
        systemctl disable headscale.service >/dev/null 2>&1 || true
      fi
      if ((HEADSCALE_WAS_ACTIVE == 1)); then
        systemctl start headscale.service >/dev/null 2>&1 || true
      fi
    else
      systemctl disable headscale.service >/dev/null 2>&1 || true
    fi
    systemctl reset-failed headscale.service >/dev/null 2>&1 || true
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap 'rollback_setup "$?" "$LINENO"' ERR

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through sudo." >&2
  exit 1
fi
[[ -s "$CONFIG" ]] || { echo "Missing $CONFIG" >&2; exit 1; }
[[ -s "$DB" ]] || { echo "Missing $DB" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates \
  curl \
  iproute2 \
  openssl \
  python3 \
  python3-venv \
  sqlite3 \
  sudo \
  ufw >/dev/null

if ! command -v nginx >/dev/null 2>&1; then
  for port in 80 443; do
    if ss -H -ltn "( sport = :$port )" 2>/dev/null | grep -q .; then
      echo "PORT_CONFLICT: tcp/$port is already occupied and nginx is not installed" >&2
      exit 1
    fi
  done
  apt-get install -y -qq nginx >/dev/null
fi
command -v nginx >/dev/null 2>&1 || {
  echo "nginx installation did not provide nginx CLI" >&2
  exit 1
}

install_certbot() {
  local existing_version=""
  if [[ -x /opt/certbot/bin/certbot ]]; then
    existing_version="$(/opt/certbot/bin/certbot --version 2>/dev/null | awk '{print $2}' || true)"
  fi

  if ! python3 - "$existing_version" "$CERTBOT_VERSION" <<'PY'
import re
import sys

def version_tuple(value: str):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', value or '')
    return tuple(int(part) for part in match.groups()) if match else ()

installed = version_tuple(sys.argv[1])
required = version_tuple(sys.argv[2])
raise SystemExit(0 if installed and installed >= required else 1)
PY
  then
    rm -rf /opt/certbot
    python3 -m venv /opt/certbot
    /opt/certbot/bin/pip install \
      --disable-pip-version-check \
      --quiet \
      "certbot==$CERTBOT_VERSION"
  fi

  ln -sfn /opt/certbot/bin/certbot /usr/local/bin/certbot
  /usr/local/bin/certbot --version >/dev/null
}
install_certbot

read -r DEVICE_DOMAIN PUBLIC_HOST < <(
  python3 - "$CONFIG" "$DB" <<'PY'
import json
import sqlite3
import sys

config_path, db_path = sys.argv[1:]
config = json.load(open(config_path, encoding="utf-8"))
with sqlite3.connect(db_path) as conn:
    row = conn.execute(
        "SELECT value FROM settings WHERE key='device_domain'"
    ).fetchone()
domain = (row[0] if row else "").strip().lower().strip(".")
if not domain:
    raise SystemExit("device_domain is not configured")
print(domain, str(config["public_host"]).strip())
PY
)
MESH_HOST="mesh.$DEVICE_DOMAIN"
MESH_BASE_DOMAIN="nodes.$DEVICE_DOMAIN"
CONTROL_URL="https://$MESH_HOST"
CGNAT_PREFIX="$(
  python3 - <<'PY'
import ipaddress
print(ipaddress.IPv4Network((0x64400000, 10)))
PY
)"

PUBLIC_IPV4="$(
  python3 - "$PUBLIC_HOST" <<'PY'
import ipaddress
import socket
import sys

value = sys.argv[1]
try:
    ip = ipaddress.ip_address(value)
    if ip.version == 4:
        print(str(ip))
        raise SystemExit
except ValueError:
    pass
for item in socket.getaddrinfo(value, None, socket.AF_INET):
    print(item[4][0])
    break
else:
    raise SystemExit("unable to resolve public IPv4")
PY
)"

MESH_IPV4="$(getent ahostsv4 "$MESH_HOST" | awk '{print $1}' | sort -u | head -n1 || true)"
if [[ "$MESH_IPV4" != "$PUBLIC_IPV4" ]]; then
  echo "DNS_NOT_READY: $MESH_HOST -> ${MESH_IPV4:-none}; expected $PUBLIC_IPV4" >&2
  exit 2
fi

if grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/conf\.d/\*\.conf;' /etc/nginx/nginx.conf; then
  NGINX_CONF=/etc/nginx/conf.d/bakunity-rdp-mesh.conf
elif grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/sites-enabled/\*;' /etc/nginx/nginx.conf; then
  NGINX_CONF=/etc/nginx/sites-enabled/bakunity-rdp-mesh.conf
else
  echo "Unsupported nginx include layout." >&2
  exit 1
fi

install -d -m 0700 "$BACKUP"
for path in \
  "$HEADSCALE_CONFIG" \
  "$HEADSCALE_POLICY" \
  "$MESH_MARKER" \
  "$MESH_KEY_HELPER" \
  "$MESH_SUDOERS" \
  "$RENEW_HOOK" \
  "$NGINX_CONF"; do
  [[ -e "$path" ]] && cp -a --parents "$path" "$BACKUP/"
done
python3 - "$DB" "$BACKUP/settings.json" <<'PY'
import json
import sqlite3
import sys

db_path, output_path = sys.argv[1:]
result = {}
with sqlite3.connect(db_path) as conn:
    for key in ("smart_route_enabled", "smart_route_control_url"):
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        result[key] = row[0] if row else None
open(output_path, "w", encoding="utf-8").write(json.dumps(result))
PY
ROLLBACK_ARMED=1

ARCH="$(dpkg --print-architecture)"
case "$ARCH" in
  amd64|arm64) ;;
  *) echo "Unsupported Headscale architecture: $ARCH" >&2; exit 1 ;;
esac

DEB="$WORK/headscale.deb"
curl -fsSL \
  "https://github.com/juanfont/headscale/releases/download/v${HEADSCALE_VERSION}/headscale_${HEADSCALE_VERSION}_linux_${ARCH}.deb" \
  -o "$DEB"
dpkg -i "$DEB" >/dev/null
systemctl stop headscale.service >/dev/null 2>&1 || true
systemctl reset-failed headscale.service >/dev/null 2>&1 || true
INSTALLED_VERSION="$(headscale version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)"
[[ "$INSTALLED_VERSION" == "$HEADSCALE_VERSION" ]] || {
  echo "Unexpected Headscale version: $INSTALLED_VERSION" >&2
  exit 1
}

install -d -o headscale -g headscale -m 0750 /var/lib/headscale
install -d -o headscale -g headscale -m 0755 /var/run/headscale
install -d -m 0755 /etc/headscale

# Previous failed boots or root-run CLI commands must never leave state unreadable
# by the packaged headscale service account.
chown -R headscale:headscale /var/lib/headscale /var/run/headscale
find /var/lib/headscale -type d -exec chmod 0750 {} +
find /var/lib/headscale -type f -exec chmod 0600 {} +
find /var/run/headscale -type d -exec chmod 0755 {} +
find /var/run/headscale -type f -exec chown headscale:headscale {} +

cat >"$HEADSCALE_POLICY" <<'EOF'
{
  "tagOwners": {
    "tag:bakunity-host": ["bakunity@"],
    "tag:bakunity-connector": ["bakunity@"]
  },
  "grants": [
    {
      "src": ["tag:bakunity-connector"],
      "dst": ["tag:bakunity-host"],
      "ip": ["tcp:3389"]
    }
  ]
}
EOF
chmod 0640 "$HEADSCALE_POLICY"
chown root:headscale "$HEADSCALE_POLICY"

cat >"$HEADSCALE_CONFIG" <<EOF
server_url: $CONTROL_URL
listen_addr: 127.0.0.1:8080
metrics_listen_addr: 127.0.0.1:9090
grpc_listen_addr: 127.0.0.1:50443
grpc_allow_insecure: false
trusted_proxies:
  - 127.0.0.1/32
  - ::1/128
noise:
  private_key_path: /var/lib/headscale/noise_private.key
prefixes:
  v4: $CGNAT_PREFIX
  v6: fd7a:115c:a1e0::/48
  allocation: sequential
derp:
  server:
    enabled: true
    region_id: 901
    region_code: bakunity
    region_name: Bakunity VPS
    verify_clients: true
    stun_listen_addr: "0.0.0.0:3478"
    private_key_path: /var/lib/headscale/derp_server_private.key
    automatically_add_embedded_derp_region: true
    ipv4: $PUBLIC_IPV4
  urls: []
  paths: []
  auto_update_enabled: false
  update_frequency: 3h
disable_check_updates: true
node:
  expiry: 0
  ephemeral:
    inactivity_timeout: 30m
  routes:
    ha:
      probe_interval: 10s
      probe_timeout: 5s
database:
  type: sqlite
  debug: false
  gorm:
    prepare_stmt: true
    parameterized_queries: true
    skip_err_record_not_found: true
    slow_threshold: 1000
  sqlite:
    path: /var/lib/headscale/db.sqlite
    write_ahead_log: true
    wal_autocheckpoint: 1000
acme_url: https://acme-v02.api.letsencrypt.org/directory
acme_email: ""
tls_letsencrypt_hostname: ""
tls_letsencrypt_cache_dir: /var/lib/headscale/cache
tls_letsencrypt_challenge_type: HTTP-01
tls_letsencrypt_listen: ":http"
tls_cert_path: ""
tls_key_path: ""
log:
  level: info
  format: text
policy:
  mode: file
  path: $HEADSCALE_POLICY
dns:
  magic_dns: false
  base_domain: $MESH_BASE_DOMAIN
  override_local_dns: false
  nameservers:
    global: []
    split: {}
  search_domains: []
  extra_records: []
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"
EOF
chmod 0640 "$HEADSCALE_CONFIG"
chown root:headscale "$HEADSCALE_CONFIG"

headscale configtest >/dev/null

systemctl stop headscale.service >/dev/null 2>&1 || true
for spec in "tcp:8080" "tcp:9090" "tcp:50443" "udp:3478"; do
  proto="${spec%%:*}"
  port="${spec##*:}"
  if [[ "$proto" == "tcp" ]]; then
    if ss -H -ltn "( sport = :$port )" 2>/dev/null | grep -q .; then
      echo "HEADSCALE_PORT_CONFLICT: tcp/$port is already occupied" >&2
      ss -H -ltnp "( sport = :$port )" >&2 || true
      exit 1
    fi
  else
    if ss -H -lun "( sport = :$port )" 2>/dev/null | grep -q .; then
      echo "HEADSCALE_PORT_CONFLICT: udp/$port is already occupied" >&2
      ss -H -lunp "( sport = :$port )" >&2 || true
      exit 1
    fi
  fi
done

systemctl enable headscale.service >/dev/null
systemctl restart headscale.service
HEADSCALE_READY=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:8080/health >/dev/null 2>&1; then
    HEADSCALE_READY=1
    break
  fi
  if systemctl is-failed --quiet headscale.service; then
    break
  fi
  sleep 1
done
if ((HEADSCALE_READY != 1)); then
  echo "HEADSCALE_STARTUP_FAILED" >&2
  stat -c 'HEADSCALE_STATE %U:%G %a %n' \
    /var/lib/headscale \
    /var/lib/headscale/derp_server_private.key \
    /var/lib/headscale/noise_private.key \
    /var/lib/headscale/db.sqlite 2>/dev/null >&2 || true
  systemctl status headscale.service --no-pager --full >&2 || true
  journalctl -u headscale.service -n 80 --no-pager -o cat >&2 || true
  exit 1
fi

if ! headscale users list 2>/dev/null | grep -Eq '(^|[[:space:]])bakunity([[:space:]]|$)'; then
  headscale users create bakunity >/dev/null
fi

install -d -m 0755 "$ACME_WEBROOT/.well-known/acme-challenge"
cat >"$NGINX_CONF" <<EOF
# Managed by Bakunity RDP Smart Route
server {
    listen 80;
    listen [::]:80;
    server_name $MESH_HOST;

    location ^~ /.well-known/acme-challenge/ {
        alias $ACME_WEBROOT/.well-known/acme-challenge/;
        default_type text/plain;
    }

    location / {
        return 404;
    }
}
EOF
chmod 0644 "$NGINX_CONF"
nginx -t
systemctl enable --now nginx >/dev/null
systemctl reload nginx

ACME_PROBE="bakunity-mesh-$(openssl rand -hex 12)"
printf '%s\n' "$ACME_PROBE" >"$ACME_WEBROOT/.well-known/acme-challenge/$ACME_PROBE"
ACME_BODY=""
for _ in $(seq 1 20); do
  ACME_BODY="$(curl -fsS --max-time 2 -H "Host: $MESH_HOST" \
    "http://127.0.0.1/.well-known/acme-challenge/$ACME_PROBE" 2>/dev/null || true)"
  [[ "$ACME_BODY" == "$ACME_PROBE" ]] && break
  sleep 0.25
done
rm -f "$ACME_WEBROOT/.well-known/acme-challenge/$ACME_PROBE"
[[ "$ACME_BODY" == "$ACME_PROBE" ]] || {
  echo "ACME_ROUTE_NOT_READY: nginx is not serving $MESH_HOST challenge webroot" >&2
  exit 1
}

/usr/local/bin/certbot certonly \
  --quiet \
  --webroot \
  --webroot-path "$ACME_WEBROOT" \
  --preferred-challenges http \
  --cert-name "$CERT_NAME" \
  --domain "$MESH_HOST" \
  --key-type rsa \
  --rsa-key-size 2048 \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email

cat >"$NGINX_CONF" <<EOF
# Managed by Bakunity RDP Smart Route
server {
    listen 80;
    listen [::]:80;
    server_name $MESH_HOST;

    location ^~ /.well-known/acme-challenge/ {
        alias $ACME_WEBROOT/.well-known/acme-challenge/;
        default_type text/plain;
    }

    location / {
        return 404;
    }
}

upstream bakunity_headscale {
    server 127.0.0.1:8080 max_fails=1 fail_timeout=5s;
    keepalive 2;
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name $MESH_HOST;

    ssl_certificate /etc/letsencrypt/live/$CERT_NAME/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$CERT_NAME/privkey.pem;

    location = /generate_204 {
        return 204;
    }

    location / {
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header True-Client-IP \$remote_addr;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_pass http://bakunity_headscale;
    }
}
EOF
chmod 0644 "$NGINX_CONF"

cat >"$RENEW_HOOK" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
nginx -t >/dev/null
systemctl reload nginx
EOF
chmod 0755 "$RENEW_HOOK"

install -m 0755 \
  /opt/hermes-rdp/source/server/bin/bakunity-rdp-mesh-key.sh \
  "$MESH_KEY_HELPER" 2>/dev/null || true
if [[ ! -x "$MESH_KEY_HELPER" ]]; then
  cat >"$MESH_KEY_HELPER" <<'EOF'
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
[[ -s "$MARKER" ]] || { echo "Smart Route mesh is not enabled" >&2; exit 3; }
[[ -x "$HEADSCALE" ]] || { echo "headscale is not installed" >&2; exit 4; }
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
EOF
  chmod 0755 "$MESH_KEY_HELPER"
fi

cat >"$MESH_SUDOERS" <<'EOF'
hermes-rdp ALL=(root) NOPASSWD: /usr/local/sbin/bakunity-rdp-mesh-key host
hermes-rdp ALL=(root) NOPASSWD: /usr/local/sbin/bakunity-rdp-mesh-key connector
EOF
chmod 0440 "$MESH_SUDOERS"
visudo -cf "$MESH_SUDOERS" >/dev/null

nginx -t
systemctl reload nginx
ufw allow 443/tcp comment 'Bakunity Smart Route control' >/dev/null || true
ufw allow 3478/udp comment 'Bakunity Smart Route STUN' >/dev/null || true

for _ in $(seq 1 30); do
  curl -fsS --max-time 3 "$CONTROL_URL/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS --max-time 3 "$CONTROL_URL/health" >/dev/null

printf 'HEADSCALE_VERSION=%s\nCONTROL_URL=%s\n' \
  "$HEADSCALE_VERSION" "$CONTROL_URL" >"$MESH_MARKER"
chmod 0640 "$MESH_MARKER"
chown root:hermes-rdp "$MESH_MARKER"

python3 - "$DB" "$CONTROL_URL" <<'PY'
import sqlite3
import sys

db_path, control_url = sys.argv[1:]
with sqlite3.connect(db_path) as conn:
    for key, value in (
        ("smart_route_enabled", "1"),
        ("smart_route_control_url", control_url),
    ):
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
PY

ROLLBACK_ARMED=0
echo "SMART_ROUTE_MESH=PASS"
echo "CONTROL_URL=$CONTROL_URL"
echo "MESH_BASE_DOMAIN=$MESH_BASE_DOMAIN"
echo "HEADSCALE_VERSION=$HEADSCALE_VERSION"
echo "HEADSCALE=$(systemctl is-active headscale.service)"
echo "STUN=udp/3478"
echo "POLICY=connector -> host:3389"
