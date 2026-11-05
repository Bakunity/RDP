#!/usr/bin/env bash
set -Eeuo pipefail

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GO_VERSION="${BAKUNITY_GO_VERSION:-1.26.10}"
CONFIG=/etc/hermes-rdp/config.json
ARTIFACT_ROOT="${BAKUNITY_TRANSPORT_ARTIFACT_ROOT:-/var/lib/hermes-rdp/native-transport-artifacts}"
BUILD_ROOT="${BAKUNITY_TRANSPORT_BUILD_ROOT:-/var/cache/bakunity-transport}"
MIN_BUILD_KB="${BAKUNITY_TRANSPORT_MIN_BUILD_KB:-2097152}"
WORK=""

cleanup() {
  [[ -n "${WORK:-}" && -d "$WORK" ]] && rm -rf "$WORK"
}
trap cleanup EXIT

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through sudo." >&2
  exit 1
fi

[[ -s "$ROOT/native-transport/go.mod" ]] || {
  echo "Missing native transport source." >&2
  exit 1
}

CLIENT_REF="${BAKUNITY_TRANSPORT_CLIENT_REF:-}"
if [[ -z "$CLIENT_REF" && -s "$CONFIG" ]]; then
  CLIENT_REF="$(
    python3 - "$CONFIG" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print(str(data.get("client_repository_ref") or data.get("repository_ref") or ""))
PY
  )"
fi
CLIENT_REF="${CLIENT_REF,,}"
if ! [[ "$CLIENT_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BAKUNITY_TRANSPORT_CLIENT_REF must be an immutable 40-character SHA." >&2
  exit 1
fi

ARTIFACT_DIR="$ARTIFACT_ROOT/$CLIENT_REF/windows-amd64"
ARTIFACT="$ARTIFACT_DIR/BakunityTransport.exe"
CHECKSUM="$ARTIFACT_DIR/BakunityTransport.exe.sha256"

if [[ -s "$ARTIFACT" && -s "$CHECKSUM" ]]; then
  EXPECTED="$(tr -d '[:space:]' < "$CHECKSUM" | tr '[:upper:]' '[:lower:]')"
  ACTUAL="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
  if [[ "$EXPECTED" =~ ^[0-9a-f]{64}$ && "$EXPECTED" == "$ACTUAL" ]]; then
    echo "WINDOWS_ARTIFACT=READY"
    echo "WINDOWS_ARTIFACT_REF=$CLIENT_REF"
    echo "WINDOWS_ARTIFACT_SHA256=$ACTUAL"
    echo "WINDOWS_ARTIFACT_PATH=$ARTIFACT"
    exit 0
  fi
fi

for command in curl tar python3 sha256sum awk df dpkg head; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Missing required command: $command" >&2
    exit 1
  }
done

install -d -m 0700 "$BUILD_ROOT"
find "$BUILD_ROOT" -mindepth 1 -maxdepth 1 -type d   -name 'windows-build.*' -mtime +1 -exec rm -rf {} + 2>/dev/null || true

AVAILABLE_KB="$(df -Pk "$BUILD_ROOT" | awk 'NR==2 {print $4}')"
AVAILABLE_INODES="$(df -Pi "$BUILD_ROOT" | awk 'NR==2 {print $4}')"
if ! [[ "$AVAILABLE_KB" =~ ^[0-9]+$ ]] || ((AVAILABLE_KB < MIN_BUILD_KB)); then
  echo "BUILD_DISK_NOT_READY: $BUILD_ROOT has ${AVAILABLE_KB:-unknown} KB free; need at least $MIN_BUILD_KB KB" >&2
  exit 1
fi
if ! [[ "$AVAILABLE_INODES" =~ ^[0-9]+$ ]] || ((AVAILABLE_INODES < 100000)); then
  echo "BUILD_INODES_NOT_READY: $BUILD_ROOT has ${AVAILABLE_INODES:-unknown} free inodes; need at least 100000" >&2
  exit 1
fi

WORK="$(mktemp -d -p "$BUILD_ROOT" windows-build.XXXXXXXX)"
install -d -m 0700 "$WORK/tmp" "$WORK/module"

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
    echo "Unsupported build host architecture: $ARCH" >&2
    exit 1
    ;;
esac

GO_TAR="$WORK/go.tar.gz"
curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz" -o "$GO_TAR"
echo "$GO_SHA256  $GO_TAR" | sha256sum -c - >/dev/null
tar -C "$WORK" -xzf "$GO_TAR"
GO="$WORK/go/bin/go"

cp -a "$ROOT/native-transport"/. "$WORK/module/"
CANDIDATE="$WORK/BakunityTransport.exe"
(
  cd "$WORK/module"
  export TMPDIR="$WORK/tmp"
  export GOTMPDIR="$WORK/tmp"
  export GOMODCACHE="$WORK/gomod"
  export GOCACHE="$WORK/gocache"
  export GOFLAGS="-p=1"
  "$GO" mod tidy
  CGO_ENABLED=0 GOOS=windows GOARCH=amd64     "$GO" build -trimpath -ldflags="-s -w -X main.transportBuildRef=$CLIENT_REF"     -o "$CANDIDATE" ./cmd/bakunity-transport
)

[[ -s "$CANDIDATE" ]] || {
  echo "Windows Bakunity Transport binary was not produced." >&2
  exit 1
}
if [[ "$(head -c 2 "$CANDIDATE")" != "MZ" ]]; then
  echo "Windows Bakunity Transport artifact is not a PE executable." >&2
  exit 1
fi

SHA256="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
install -d -o root -g hermes-rdp -m 0750 "$ARTIFACT_DIR"
install -o root -g hermes-rdp -m 0640 "$CANDIDATE" "$ARTIFACT"
printf '%s\n' "$SHA256" > "$CHECKSUM"
chown root:hermes-rdp "$CHECKSUM"
chmod 0640 "$CHECKSUM"

echo "WINDOWS_ARTIFACT=PASS"
echo "WINDOWS_ARTIFACT_REF=$CLIENT_REF"
echo "WINDOWS_ARTIFACT_SHA256=$SHA256"
echo "WINDOWS_ARTIFACT_PATH=$ARTIFACT"
