#!/usr/bin/env bash
set -Eeuo pipefail

REPO="bakunity/RDP"
REF="${BAKUNITY_RDP_REF:-${HERMES_RDP_REF:-main}}"
HOST=""
TELEGRAM_TOKEN=""
TELEGRAM_CHAT_ID=""
API_PORT=7443
SSH_PORT=7000
PORT_START=53389
PORT_END=53420
MIGRATE=0
TRUSTED_RDP_CERT=0
AUTODEPLOY="${BAKUNITY_RDP_AUTODEPLOY:-0}"
SSH_USER="hermes-tunnel"

usage() {
  cat <<'EOF'
Usage:
  install-server.sh --host HOST [--telegram-token TOKEN --telegram-chat-id ID] [options]

Options:
  --api-port PORT       HTTPS API port (default: 7443)
  --ssh-port PORT       dedicated OpenSSH tunnel port (default: 7000)
  --frp-port PORT       compatibility alias for --ssh-port
  --port-start PORT     first RDP port (default: 53389)
  --port-end PORT       last RDP port (default: 53420)
  --trusted-rdp-cert    enable trusted public-IP RDP certificate lifecycle
  --autodeploy          track this non-main branch and deploy only green CI commits
  --migrate             replace an existing legacy FRP installation
EOF
}

while (($#)); do
  case "$1" in
    --host) HOST="${2:?}"; shift 2 ;;
    --telegram-token) TELEGRAM_TOKEN="${2:?}"; shift 2 ;;
    --telegram-chat-id) TELEGRAM_CHAT_ID="${2:?}"; shift 2 ;;
    --api-port) API_PORT="${2:?}"; shift 2 ;;
    --ssh-port|--frp-port) SSH_PORT="${2:?}"; shift 2 ;;
    --port-start) PORT_START="${2:?}"; shift 2 ;;
    --port-end) PORT_END="${2:?}"; shift 2 ;;
    --trusted-rdp-cert) TRUSTED_RDP_CERT=1; shift ;;
    --autodeploy) AUTODEPLOY=1; shift ;;
    --migrate) MIGRATE=1; shift ;;
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
if [[ -n "$TELEGRAM_TOKEN" || -n "$TELEGRAM_CHAT_ID" ]]; then
  if [[ -z "$TELEGRAM_TOKEN" || -z "$TELEGRAM_CHAT_ID" ]]; then
    echo "telegram-token and telegram-chat-id must be provided together." >&2
    exit 2
  fi
fi
if ! [[ "$API_PORT" =~ ^[0-9]+$ && "$SSH_PORT" =~ ^[0-9]+$ && "$PORT_START" =~ ^[0-9]+$ && "$PORT_END" =~ ^[0-9]+$ ]]; then
  echo "Ports must be integers." >&2
  exit 2
fi
if ((PORT_START > PORT_END)); then
  echo "port-start must not exceed port-end." >&2
  exit 2
fi
if ((API_PORT == SSH_PORT)); then
  echo "API and SSH tunnel ports must be different." >&2
  exit 2
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="/var/backups/hermes-rdp/$STAMP"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates \
  curl \
  git \
  openssl \
  openssh-server \
  python3 \
  sudo \
  ufw \
  iproute2 >/dev/null

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
SOURCE_ROOT=""
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../server/pyproject.toml" ]]; then
  SOURCE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  ARCHIVE="$WORK_DIR/source.tar.gz"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$ARCHIVE"
  tar -xzf "$ARCHIVE" -C "$WORK_DIR"
  SOURCE_ROOT="$(find "$WORK_DIR" -maxdepth 1 -mindepth 1 -type d -name 'RDP-*' | head -n1)"
fi
if [[ -z "$SOURCE_ROOT" || ! -f "$SOURCE_ROOT/server/pyproject.toml" ]]; then
  echo "Unable to locate project source." >&2
  exit 1
fi

if ((TRUSTED_RDP_CERT == 1)); then
  if [[ ! -f "$SOURCE_ROOT/scripts/setup-trusted-rdp-cert.sh" ]]; then
    echo "Trusted RDP certificate module is missing from source." >&2
    exit 1
  fi
  python3 - "$HOST" <<'PY'
import ipaddress
import sys

value = ipaddress.ip_address(sys.argv[1])
if value.version != 4 or not value.is_global:
    raise SystemExit('--trusted-rdp-cert requires --host to be a globally routable public IPv4 address')
PY
fi

install -d -m 0700 "$BACKUP_DIR"
for path in \
  /etc/frp \
  /etc/hermes-rdp \
  /opt/hermes-rdp \
  /var/lib/hermes-rdp \
  /etc/systemd/system/frps.service \
  /etc/systemd/system/hermes-rdp-sshd.service \
  /etc/systemd/system/hermes-rdp.service \
  /etc/systemd/system/hermes-rdp-cert-renew.service \
  /etc/systemd/system/hermes-rdp-cert-renew.timer \
  /etc/systemd/system/hermes-rdp-autodeploy.service \
  /etc/systemd/system/hermes-rdp-autodeploy.timer \
  /usr/local/sbin/hermes-rdp-autodeploy \
  /usr/local/sbin/hermes-rdp-autodeploy-control \
  /usr/local/sbin/hermes-rdp-cert-renew \
  /etc/sudoers.d/hermes-rdp-autodeploy-control \
  /etc/sudoers.d/hermes-rdp; do
  if [[ -e "$path" ]]; then
    cp -a --parents "$path" "$BACKUP_DIR/"
  fi
done
ln -sfn "$BACKUP_DIR" /var/backups/hermes-rdp/latest

if systemctl list-unit-files frps.service >/dev/null 2>&1; then
  if ((MIGRATE == 0)) && systemctl is-enabled frps.service >/dev/null 2>&1; then
    echo "Existing Hermes FRP service detected." >&2
    echo "Re-run with --migrate after reviewing backup: $BACKUP_DIR" >&2
    exit 1
  fi
  systemctl disable --now frps.service 2>/dev/null || true
fi

getent group hermes-rdp >/dev/null || groupadd --system hermes-rdp
id hermes-rdp >/dev/null 2>&1 || useradd \
  --system \
  --gid hermes-rdp \
  --home-dir /var/lib/hermes-rdp \
  --shell /usr/sbin/nologin \
  hermes-rdp

getent group "$SSH_USER" >/dev/null || groupadd --system "$SSH_USER"
id "$SSH_USER" >/dev/null 2>&1 || useradd \
  --system \
  --gid "$SSH_USER" \
  --home-dir /var/lib/hermes-rdp-tunnel \
  --create-home \
  --shell /usr/sbin/nologin \
  "$SSH_USER"

TUNNEL_PASSWORD="$(openssl rand -hex 32)"
TUNNEL_HASH="$(openssl passwd -6 "$TUNNEL_PASSWORD")"
unset TUNNEL_PASSWORD
usermod --password "$TUNNEL_HASH" "$SSH_USER"
unset TUNNEL_HASH

install -d -m 0755 -o root -g root /opt/hermes-rdp/app
rm -rf /opt/hermes-rdp/app/hermes_rdp
cp -a "$SOURCE_ROOT/server/hermes_rdp" /opt/hermes-rdp/app/hermes_rdp
chown -R root:root /opt/hermes-rdp/app

cat > /usr/local/bin/hermes-rdpctl <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/opt/hermes-rdp/app
exec /usr/bin/python3 -m hermes_rdp.cli "$@"
EOF
chmod 0755 /usr/local/bin/hermes-rdpctl
# New public CLI; legacy wrapper remains for existing automations.
cat > /usr/local/bin/bakunity-rdpctl <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/hermes-rdp/app
exec /usr/bin/python3 -m hermes_rdp.cli "$@"
EOF
chmod 0755 /usr/local/bin/bakunity-rdpctl

cat > /usr/local/bin/hermes-rdp-authorized-keys <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/opt/hermes-rdp/app
exec /usr/bin/python3 -m hermes_rdp.authorized_keys "$@"
EOF
chmod 0755 /usr/local/bin/hermes-rdp-authorized-keys

install -d -m 0750 -o root -g hermes-rdp /etc/hermes-rdp
install -d -m 0750 -o root -g hermes-rdp /etc/hermes-rdp/tls
install -d -m 0750 -o hermes-rdp -g hermes-rdp /var/lib/hermes-rdp

if [[ -n "$TELEGRAM_TOKEN" ]]; then
  printf '%s\n' "$TELEGRAM_TOKEN" > /etc/hermes-rdp/telegram-token
else
  : > /etc/hermes-rdp/telegram-token
fi
chmod 0640 /etc/hermes-rdp/telegram-token
chown root:hermes-rdp /etc/hermes-rdp/telegram-token

if [[ ! -s /etc/hermes-rdp/web-admin-token ]]; then
  openssl rand -hex 32 > /etc/hermes-rdp/web-admin-token
fi
chmod 0640 /etc/hermes-rdp/web-admin-token
chown root:hermes-rdp /etc/hermes-rdp/web-admin-token

API_TLS_DIR=/etc/hermes-rdp/tls
if [[ ! -s "$API_TLS_DIR/api.key" || ! -s "$API_TLS_DIR/api.crt" ]]; then
  SAN="DNS:$HOST"
  if [[ "$HOST" =~ ^[0-9a-fA-F:.]+$ ]]; then
    SAN="IP:$HOST"
  fi
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
    -subj "/CN=$HOST" \
    -addext "subjectAltName=$SAN" \
    -keyout "$API_TLS_DIR/api.key" \
    -out "$API_TLS_DIR/api.crt" >/dev/null 2>&1
fi
openssl x509 \
  -in "$API_TLS_DIR/api.crt" \
  -outform DER |
  sha256sum |
  awk '{print toupper($1)}' > "$API_TLS_DIR/api.sha256"

chmod 0640 "$API_TLS_DIR/api.key"
chmod 0644 "$API_TLS_DIR/api.crt" "$API_TLS_DIR/api.sha256"
chown root:hermes-rdp \
  "$API_TLS_DIR/api.key" \
  "$API_TLS_DIR/api.crt" \
  "$API_TLS_DIR/api.sha256"

SSH_HOST_KEY=/etc/hermes-rdp/ssh_host_ed25519_key
if [[ ! -s "$SSH_HOST_KEY" || ! -s "$SSH_HOST_KEY.pub" ]]; then
  rm -f "$SSH_HOST_KEY" "$SSH_HOST_KEY.pub"
  ssh-keygen -q -t ed25519 -N '' -C 'Hermes RDP tunnel host' -f "$SSH_HOST_KEY"
fi
chmod 0600 "$SSH_HOST_KEY"
chmod 0644 "$SSH_HOST_KEY.pub"
chown root:root "$SSH_HOST_KEY"
chown root:hermes-rdp "$SSH_HOST_KEY.pub"
install \
  -m 0644 \
  -o root \
  -g hermes-rdp \
  "$SSH_HOST_KEY.pub" \
  /etc/hermes-rdp/ssh-host-key.pub

cat > /etc/hermes-rdp/config.json <<EOF
{
  "public_host": "$HOST",
  "api_port": $API_PORT,
  "ssh_bind_port": $SSH_PORT,
  "ssh_user": "$SSH_USER",
  "port_start": $PORT_START,
  "port_end": $PORT_END,
  "telegram_chat_id": "$TELEGRAM_CHAT_ID",
  "web_admin_token_file": "/etc/hermes-rdp/web-admin-token",
  "web_admin_credentials_file": "/etc/hermes-rdp/web-admin-credentials.json",
  "ssh_host_key_file": "/etc/hermes-rdp/ssh-host-key.pub",
  "close_tunnel_helper": "/usr/local/sbin/hermes-rdp-close-tunnel",
  "client_installer_url": "https://raw.githubusercontent.com/$REPO/$REF/scripts/install-client.ps1",
  "repository_ref": "$REF",
  "repository_requested_ref": "$REF",
  "client_repository_ref": "$REF",
  "client_compatible_refs": ["$REF"]
}
EOF
chmod 0640 /etc/hermes-rdp/config.json
chown root:hermes-rdp /etc/hermes-rdp/config.json

cat > /etc/hermes-rdp/sshd_config <<EOF
Port $SSH_PORT
ListenAddress 0.0.0.0
AddressFamily inet
HostKey /etc/hermes-rdp/ssh_host_ed25519_key
PidFile /run/hermes-rdp-sshd.pid

AllowUsers $SSH_USER
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
UsePAM no

AuthorizedKeysFile none
AuthorizedKeysCommand /usr/local/bin/hermes-rdp-authorized-keys %u %t %k
AuthorizedKeysCommandUser hermes-rdp

AllowTcpForwarding remote
AllowStreamLocalForwarding no
GatewayPorts clientspecified
PermitOpen none
PermitTTY no
X11Forwarding no
AllowAgentForwarding no
PermitTunnel no
PermitUserEnvironment no
PermitUserRC no
MaxSessions 0

ClientAliveInterval 30
ClientAliveCountMax 3
LoginGraceTime 20
MaxAuthTries 3
TCPKeepAlive yes
UseDNS no
StrictModes yes
LogLevel VERBOSE
EOF
chmod 0640 /etc/hermes-rdp/sshd_config
chown root:hermes-rdp /etc/hermes-rdp/sshd_config
/usr/sbin/sshd -t -f /etc/hermes-rdp/sshd_config

install -m 0755 \
  "$SOURCE_ROOT/server/bin/hermes-rdp-close-tunnel.sh" \
  /usr/local/sbin/hermes-rdp-close-tunnel

cat > /etc/sudoers.d/hermes-rdp <<'EOF'
hermes-rdp ALL=(root) NOPASSWD: /usr/local/sbin/hermes-rdp-close-tunnel *
EOF
chmod 0440 /etc/sudoers.d/hermes-rdp
visudo -cf /etc/sudoers.d/hermes-rdp >/dev/null

install \
  -m 0644 \
  "$SOURCE_ROOT/server/systemd/hermes-rdp-sshd.service" \
  /etc/systemd/system/hermes-rdp-sshd.service
install \
  -m 0644 \
  "$SOURCE_ROOT/server/systemd/hermes-rdp.service" \
  /etc/systemd/system/hermes-rdp.service
install \
  -m 0644 \
  "$SOURCE_ROOT/server/systemd/bakunity-rdp-default.service" \
  /etc/systemd/system/bakunity-rdp-default.service
install \
  -m 0644 \
  "$SOURCE_ROOT/server/systemd/hermes-rdp-autodeploy.service" \
  /etc/systemd/system/hermes-rdp-autodeploy.service
install \
  -m 0644 \
  "$SOURCE_ROOT/server/systemd/hermes-rdp-autodeploy.timer" \
  /etc/systemd/system/hermes-rdp-autodeploy.timer
install \
  -m 0755 \
  "$SOURCE_ROOT/server/bin/hermes-rdp-autodeploy.sh" \
  /usr/local/sbin/hermes-rdp-autodeploy
install \
  -m 0755 \
  "$SOURCE_ROOT/server/bin/hermes-rdp-autodeploy-control.sh" \
  /usr/local/sbin/hermes-rdp-autodeploy-control
install \
  -m 0440 \
  "$SOURCE_ROOT/server/sudoers/hermes-rdp-autodeploy-control" \
  /etc/sudoers.d/hermes-rdp-autodeploy-control
visudo -cf /etc/sudoers.d/hermes-rdp-autodeploy-control >/dev/null

if ((MIGRATE == 1)); then
  rm -f /etc/systemd/system/frps.service /usr/local/bin/frps
  rm -rf /etc/frp
fi

ufw allow "$SSH_PORT/tcp" comment 'Hermes RDP OpenSSH' >/dev/null || true
ufw allow "$API_PORT/tcp" comment 'Hermes RDP API' >/dev/null || true
ufw allow "$PORT_START:$PORT_END/tcp" comment 'Hermes RDP devices' >/dev/null || true
ufw allow "3389/tcp" comment 'Bakunity RDP default device' >/dev/null || true

PYTHONPATH=/opt/hermes-rdp/app \
  python3 -m compileall -q /opt/hermes-rdp/app/hermes_rdp

systemctl daemon-reload
systemctl enable hermes-rdp-sshd.service hermes-rdp.service
if [[ "$AUTODEPLOY" == "1" ]]; then
  if [[ "$REF" == "main" || "$REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "--autodeploy requires a mutable non-main branch ref." >&2
    exit 2
  fi
  touch /etc/hermes-rdp/autodeploy.enabled
  chmod 0644 /etc/hermes-rdp/autodeploy.enabled
  systemctl enable hermes-rdp-autodeploy.timer
else
  rm -f /etc/hermes-rdp/autodeploy.enabled
  systemctl disable hermes-rdp-autodeploy.timer >/dev/null 2>&1 || true
fi
systemctl restart hermes-rdp-sshd.service hermes-rdp.service
if [[ "$AUTODEPLOY" == "1" ]]; then
  systemctl start hermes-rdp-autodeploy.timer
fi
sleep 3

if ((MIGRATE == 1)); then
  PYTHONPATH=/opt/hermes-rdp/app python3 - <<'PY'
from hermes_rdp.config import load_config
from hermes_rdp.db import Registry

config = load_config()
registry = Registry(config.db_path, config.port_start, config.port_end)
with registry.connect() as conn:
    conn.execute(
        "DELETE FROM devices "
        "WHERE revoked=1 OR ssh_public_key IS NULL OR ssh_public_key=''"
    )
PY
  systemctl restart hermes-rdp.service
  sleep 2
fi

if ((TRUSTED_RDP_CERT == 1)); then
  bash "$SOURCE_ROOT/scripts/setup-trusted-rdp-cert.sh" --host "$HOST"
fi

echo
echo "=== HERMES RDP OPENSSH INSTALLED ==="
echo "backup=$BACKUP_DIR"
echo "api=https://$HOST:$API_PORT"
echo "api_fingerprint=$(cat "$API_TLS_DIR/api.sha256")"
echo "ssh_tunnel_port=$SSH_PORT"
echo "rdp_ports=$PORT_START-$PORT_END"
echo "ssh_tunnel=$(systemctl is-active hermes-rdp-sshd.service)"
echo "controller=$(systemctl is-active hermes-rdp.service)"
echo "autodeploy=$(if [[ -e /etc/hermes-rdp/autodeploy.enabled ]]; then systemctl is-active hermes-rdp-autodeploy.timer; else echo disabled; fi)"
echo "web_ui=https://$HOST:$API_PORT/admin/"
echo "web_admin_login=admin"
echo "web_admin_password_setup=bakunity-rdpctl admin password --generate"
if ((TRUSTED_RDP_CERT == 1)); then
  echo "trusted_rdp_certificate=$(systemctl is-active hermes-rdp-cert-renew.timer)"
fi
echo
echo "Create the first PC code while preserving port $PORT_START:"
echo "  sudo bakunity-rdpctl pair create --name 'Windows-PC-01' --port $PORT_START"
echo
echo "Then send /start to the Telegram bot."
