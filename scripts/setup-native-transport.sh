#!/usr/bin/env bash
set -Eeuo pipefail

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GO_VERSION="${BAKUNITY_GO_VERSION:-1.26.10}"
CONFIG=/etc/hermes-rdp/config.json
DB=/var/lib/hermes-rdp/state.sqlite3
BIN=/usr/local/bin/bakunity-transport
UNIT=/etc/systemd/system/bakunity-transport.service
STATE=/var/lib/bakunity-transport
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through sudo." >&2
  exit 1
fi

[[ -s "$CONFIG" ]] || { echo "Missing $CONFIG" >&2; exit 1; }
[[ -s "$DB" ]] || { echo "Missing $DB" >&2; exit 1; }
[[ -s "$ROOT/native-transport/go.mod" ]] || {
  echo "Missing native transport source." >&2
  exit 1
}

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl python3 sqlite3 tar ufw >/dev/null

ARCH="$(dpkg --print-architecture)"
case "$ARCH" in
  amd64)
    GO_ARCH=amd64
    GO_SHA256=ccfe7ae822d2c2f41f4fe7c956199967a4dac22d0ee0d2b2bfdb440aab3b20c5
    ;;
  arm64)
    GO_ARCH=arm64
    GO_SHA256=3f4227ce7b206a513e794f1393adb473a07b46e94d18bd15d1c684bbb7319797
    ;;
  *)
    echo "Unsupported architecture: $ARCH" >&2
    exit 1
    ;;
esac

GO_TAR="$WORK/go.tar.gz"
curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz" -o "$GO_TAR"
echo "$GO_SHA256  $GO_TAR" | sha256sum -c - >/dev/null
tar -C "$WORK" -xzf "$GO_TAR"
GO="$WORK/go/bin/go"

BUILD="$WORK/bakunity-transport"
(
  cd "$ROOT/native-transport"
  GOMODCACHE="$WORK/gomod" GOCACHE="$WORK/gocache" \
    "$GO" build -trimpath -ldflags='-s -w' \
    -o "$BUILD" ./cmd/bakunity-transport
)
"$BUILD" id --identity "$WORK/test-identity.key" >/dev/null

if ! getent passwd bakunity-transport >/dev/null; then
  useradd \
    --system \
    --home "$STATE" \
    --shell /usr/sbin/nologin \
    bakunity-transport
fi
install -d -o bakunity-transport -g bakunity-transport -m 0750 "$STATE"
install -m 0755 "$BUILD" "$BIN"
install -m 0644 "$ROOT/server/systemd/bakunity-transport.service" "$UNIT"

systemctl daemon-reload
systemctl enable bakunity-transport.service >/dev/null
systemctl restart bakunity-transport.service

READY=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 http://127.0.0.1:7445/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  if systemctl is-failed --quiet bakunity-transport.service; then
    break
  fi
  sleep 0.5
done
if ((READY != 1)); then
  systemctl status bakunity-transport.service --no-pager --full >&2 || true
  journalctl -u bakunity-transport.service -n 80 --no-pager -o cat >&2 || true
  exit 1
fi

STATUS="$(curl -fsS http://127.0.0.1:7445/status)"
read -r PEER_ID PUBLIC_HOST < <(
  python3 - "$STATUS" "$CONFIG" <<'PY'
import json
import sys
status = json.loads(sys.argv[1])
config = json.load(open(sys.argv[2], encoding="utf-8"))
peer_id = str(status.get("peer_id") or "").strip()
public_host = str(config.get("public_host") or "").strip()
if not peer_id or not public_host:
    raise SystemExit("missing relay identity/public host")
print(peer_id, public_host)
PY
)

RELAY_ADDR="$(
  python3 - "$PUBLIC_HOST" "$PEER_ID" <<'PY'
import ipaddress
import sys
host, peer = sys.argv[1:]
try:
    ip = ipaddress.ip_address(host)
    prefix = "/ip4" if ip.version == 4 else "/ip6"
    print(f"{prefix}/{ip}/tcp/7444/p2p/{peer}")
except ValueError:
    print(f"/dns4/{host}/tcp/7444/p2p/{peer}")
PY
)"

python3 - "$DB" "$RELAY_ADDR" <<'PY'
import sqlite3
import sys
db_path, relay_addr = sys.argv[1:]
with sqlite3.connect(db_path) as conn:
    for key, value in (
        ("native_transport_enabled", "1"),
        ("native_transport_relay_addr", relay_addr),
    ):
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
PY

ufw allow 7444/tcp comment 'Bakunity Transport TCP' >/dev/null || true
ufw allow 7444/udp comment 'Bakunity Transport QUIC' >/dev/null || true

echo "BAKUNITY_TRANSPORT=PASS"
echo "SERVICE=$(systemctl is-active bakunity-transport.service)"
echo "RELAY_ADDR=$RELAY_ADDR"
echo "CONTROL=http://127.0.0.1:7445"
