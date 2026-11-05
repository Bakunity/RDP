#!/usr/bin/env bash
set -Eeuo pipefail

REPO="bakunity/RDP"
REF="${BAKUNITY_RDP_REF:-${HERMES_RDP_REF:-main}}"
CONFIG=/etc/hermes-rdp/config.json
DB=/var/lib/hermes-rdp/state.sqlite3

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through sudo." >&2
  exit 1
fi
if [[ ! -s "$CONFIG" ]]; then
  echo "Bakunity RDP is not installed." >&2
  exit 1
fi
if [[ ! -s "$DB" ]]; then
  echo "Bakunity RDP database is missing or empty." >&2
  exit 1
fi
if ! python3 - <<'PY'
import json
with open("/etc/hermes-rdp/config.json", encoding="utf-8") as handle:
    data = json.load(handle)
raise SystemExit(0 if "ssh_bind_port" in data else 1)
PY
then
  echo "This server still uses FRP." >&2
  echo "Run install-server.sh with --migrate for the v1.1 OpenSSH migration." >&2
  exit 2
fi

TRUSTED_CERT_ENABLED="$(python3 - <<'PY'
import json
with open('/etc/hermes-rdp/config.json', encoding='utf-8') as handle:
    data = json.load(handle)
trusted = data.get('trusted_rdp_certificate') or {}
print(1 if trusted.get('enabled') is True else 0)
PY
)"

DB_UID="$(stat -c '%u' "$DB")"
DB_GID="$(stat -c '%g' "$DB")"
DB_MODE="$(stat -c '%a' "$DB")"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/hermes-rdp/update-$STAMP"
WORK="$(mktemp -d)"
ROLLBACK_ARMED=0
RESOLVED_SHA=""
DEFAULT_RDP_WAS_ACTIVE=0
if systemctl is-active --quiet bakunity-rdp-default.service 2>/dev/null; then
  DEFAULT_RDP_WAS_ACTIVE=1
fi

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT

wait_health() {
  local api_port code
  api_port="$(python3 - <<'PY'
import json
with open("/etc/hermes-rdp/config.json", encoding="utf-8") as handle:
    print(int(json.load(handle).get("api_port", 7443)))
PY
)"
  for _ in $(seq 1 30); do
    code="$(curl -sk --max-time 2 -o /dev/null -w '%{http_code}' \
      "https://127.0.0.1:${api_port}/healthz" 2>/dev/null || true)"
    if [[ "$code" == "200" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

client_bundle_hash() {
  local root="$1"
  python3 - "$root" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
paths = [
    "client/HermesRdpAgent.ps1",
    "client/HermesRdpMaintenance.ps1",
    "client/HermesRdpCertRotation.ps1",
    "client/BakunityMesh.ps1",
    "client/BakunityNativeTransport.ps1",
    "client/BakunityHostSmartRoute.ps1",
    "client/BakunitySmartRoute.ps1",
    "client/BakunitySmartRouteLaunch.ps1",
    "scripts/setup-smart-route-host.ps1",
    "scripts/install-smart-route-connector.ps1",
    "native-transport/go.mod",
    "native-transport/cmd/bakunity-transport/main.go",
    "scripts/install-client.ps1",
    "scripts/install-client-core.ps1",
    "scripts/install-client-replace.ps1",
    "scripts/repair-client.ps1",
    "scripts/repair-client-core.ps1",
    "scripts/update-client.ps1",
    "scripts/setup-client-cert-rotation.ps1",
    "scripts/sync-rdp-certificate.ps1",
    "scripts/uninstall-client.ps1",
    "scripts/uninstall-client-core.ps1",
]
digest = hashlib.sha256()
for relative in paths:
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"missing client bundle file: {relative}")
    digest.update(relative.encode("utf-8") + b"\0")
    digest.update(path.read_bytes())
print(digest.hexdigest())
PY
}
restore_optional_file() {
  local path="$1"
  rm -f "$path"
  if [[ -e "$BACKUP$path" ]]; then
    install -d -m 0755 "$(dirname "$path")"
    cp -a "$BACKUP$path" "$path"
  fi
}

rollback_update() {
  local status="$1" line="$2" rollback_ok=1
  trap - ERR
  set +e

  if ((ROLLBACK_ARMED == 0)); then
    echo "Update failed before deployment at line $line; no rollback required." >&2
    exit "$status"
  fi

  echo "Update failed at line $line; restoring $BACKUP" >&2
  systemctl stop hermes-rdp.service hermes-rdp-sshd.service >/dev/null 2>&1 || true
  systemctl stop bakunity-rdp-default.service >/dev/null 2>&1 || true

  rm -rf /opt/hermes-rdp
  cp -a "$BACKUP/opt/hermes-rdp" /opt/ || rollback_ok=0
  cp -a "$BACKUP/etc/hermes-rdp/config.json" /etc/hermes-rdp/config.json || rollback_ok=0
  cp -a "$BACKUP/etc/hermes-rdp/sshd_config" /etc/hermes-rdp/sshd_config || rollback_ok=0
  cp -a "$BACKUP/etc/systemd/system/hermes-rdp.service" \
    /etc/systemd/system/hermes-rdp.service || rollback_ok=0
  cp -a "$BACKUP/etc/systemd/system/hermes-rdp-sshd.service" \
    /etc/systemd/system/hermes-rdp-sshd.service || rollback_ok=0

  restore_optional_file /etc/systemd/system/bakunity-rdp-default.service || rollback_ok=0
  restore_optional_file /usr/local/sbin/hermes-rdp-cert-package || rollback_ok=0
  restore_optional_file /usr/local/sbin/hermes-rdp-device-cert-package || rollback_ok=0
  restore_optional_file /usr/local/sbin/hermes-rdp-cert-renew || rollback_ok=0
  restore_optional_file /usr/local/sbin/hermes-rdp-cert-state-refresh || rollback_ok=0
  restore_optional_file /usr/local/sbin/bakunity-rdp-mesh-key || rollback_ok=0
  restore_optional_file /etc/sudoers.d/bakunity-rdp-mesh-key || rollback_ok=0
  restore_optional_file /usr/local/bin/hermes-rdpctl || rollback_ok=0
  restore_optional_file /usr/local/bin/bakunity-rdpctl || rollback_ok=0
  restore_optional_file /etc/sudoers.d/hermes-rdp-cert-package || rollback_ok=0
  restore_optional_file /etc/hermes-rdp/trusted-rdp-cert-state.json || rollback_ok=0

  if [[ -s "$BACKUP/var/lib/hermes-rdp/state.sqlite3" ]]; then
    rm -f "$DB" "$DB-wal" "$DB-shm"
    install \
      -o "$DB_UID" \
      -g "$DB_GID" \
      -m "$DB_MODE" \
      "$BACKUP/var/lib/hermes-rdp/state.sqlite3" \
      "$DB" || rollback_ok=0
  else
    rollback_ok=0
  fi

  systemctl daemon-reload || rollback_ok=0
  /usr/sbin/sshd -t -f /etc/hermes-rdp/sshd_config || rollback_ok=0
  if [[ -e /etc/sudoers.d/hermes-rdp-cert-package ]]; then
    visudo -cf /etc/sudoers.d/hermes-rdp-cert-package >/dev/null || rollback_ok=0
  fi
  if [[ -e /etc/sudoers.d/bakunity-rdp-mesh-key ]]; then
    visudo -cf /etc/sudoers.d/bakunity-rdp-mesh-key >/dev/null || rollback_ok=0
  fi
  systemctl restart hermes-rdp-sshd.service hermes-rdp.service || rollback_ok=0
  if ((DEFAULT_RDP_WAS_ACTIVE == 1)); then
    systemctl restart bakunity-rdp-default.service || rollback_ok=0
  fi
  systemctl is-active --quiet hermes-rdp-sshd.service || rollback_ok=0
  systemctl is-active --quiet hermes-rdp.service || rollback_ok=0
  wait_health || rollback_ok=0

  if ((rollback_ok == 1)); then
    echo "ROLLBACK=PASS backup=$BACKUP" >&2
  else
    echo "ROLLBACK=FAIL manual recovery required from $BACKUP" >&2
  fi
  exit "$status"
}
trap 'rollback_update "$?" "$LINENO"' ERR

if [[ "$REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
  RESOLVED_SHA="${REF,,}"
else
  REF_ENCODED="$(python3 - "$REF" <<'PY'
import sys
from urllib.parse import quote
print(quote(sys.argv[1], safe=""))
PY
)"
  RESOLVED_SHA="$(
    curl -fsSL \
      -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/$REPO/commits/$REF_ENCODED" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])'
  )"
fi
if ! [[ "$RESOLVED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Unable to resolve repository ref to an immutable commit SHA." >&2
  exit 1
fi

curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$RESOLVED_SHA" -o "$WORK/source.tar.gz"
tar -xzf "$WORK/source.tar.gz" -C "$WORK"
ROOT="$(find "$WORK" -maxdepth 1 -mindepth 1 -type d -name 'RDP-*' | head -n1)"
test -f "$ROOT/server/pyproject.toml"
test -f "$ROOT/server/systemd/hermes-rdp.service"
test -f "$ROOT/server/systemd/hermes-rdp-sshd.service"
test -f "$ROOT/server/systemd/bakunity-rdp-default.service"
test -f "$ROOT/server/bin/bakunity-rdp-mesh-key.sh"
test -f "$ROOT/server/sudoers/bakunity-rdp-mesh-key"
test -f "$ROOT/client/BakunityMesh.ps1"
test -f "$ROOT/client/BakunityNativeTransport.ps1"
test -f "$ROOT/client/BakunityHostSmartRoute.ps1"
test -f "$ROOT/native-transport/go.mod"
test -f "$ROOT/native-transport/cmd/bakunity-transport/main.go"
test -f "$ROOT/scripts/setup-native-transport.sh"
test -f "$ROOT/scripts/build-native-transport-windows.sh"
test -f "$ROOT/server/systemd/bakunity-transport.service"
test -f "$ROOT/client/BakunitySmartRoute.ps1"
test -f "$ROOT/client/BakunitySmartRouteLaunch.ps1"
test -f "$ROOT/scripts/setup-smart-route-host.ps1"
test -f "$ROOT/scripts/install-smart-route-connector.ps1"
if ((TRUSTED_CERT_ENABLED == 1)); then
  test -f "$ROOT/server/bin/hermes-rdp-cert-package.sh"
  test -f "$ROOT/server/bin/hermes-rdp-device-cert-package.sh"
  test -f "$ROOT/server/bin/hermes-rdp-cert-renew.sh"
  test -f "$ROOT/server/bin/hermes-rdp-cert-state-refresh.sh"
  test -f "$ROOT/server/sudoers/hermes-rdp-cert-package"
fi
PYTHONPATH="$ROOT/server" python3 -m compileall -q "$ROOT/server/hermes_rdp"

read -r PREVIOUS_REF CONFIG_CLIENT_REF CONFIG_COMPATIBLE_REFS < <(python3 - <<'PY'
import json
with open("/etc/hermes-rdp/config.json", encoding="utf-8") as handle:
    data = json.load(handle)
compatible = [
    str(item).strip().lower()
    for item in (data.get("client_compatible_refs") or [])
    if str(item).strip()
][:32]
print(
    str(data.get("repository_ref", "")),
    str(data.get("client_repository_ref", "")),
    ",".join(compatible),
)
PY
)
PREVIOUS_CLIENT_REF="$CONFIG_CLIENT_REF"

TELEMETRY_CLIENT_REFS="$(python3 - "$DB" <<'PY'
import collections
import json
import re
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
counter = collections.Counter()
try:
    rows = connection.execute(
        "SELECT telemetry_json FROM devices "
        "WHERE revoked=0 AND telemetry_json IS NOT NULL"
    ).fetchall()
finally:
    connection.close()

for (raw,) in rows:
    try:
        telemetry = json.loads(raw or "{}")
    except Exception:
        continue
    ref = str(telemetry.get("client_repository_ref") or "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        counter[ref] += 1

print(" ".join(ref for ref, _ in counter.most_common(32)))
PY
)"

TARGET_CLIENT_HASH="$(client_bundle_hash "$ROOT")"
declare -a CANDIDATE_CLIENT_REFS=()
declare -a COMPATIBLE_CLIENT_REFS=()

add_candidate_client_ref() {
  local ref="${1,,}" existing
  [[ "$ref" =~ ^[0-9a-f]{40}$ ]] || return 0
  for existing in "${CANDIDATE_CLIENT_REFS[@]:-}"; do
    [[ "$existing" == "$ref" ]] && return 0
  done
  CANDIDATE_CLIENT_REFS+=("$ref")
}

add_compatible_client_ref() {
  local ref="${1,,}" existing
  [[ "$ref" =~ ^[0-9a-f]{40}$ ]] || return 0
  for existing in "${COMPATIBLE_CLIENT_REFS[@]:-}"; do
    [[ "$existing" == "$ref" ]] && return 0
  done
  COMPATIBLE_CLIENT_REFS+=("$ref")
}

client_bundle_hash_for_ref() {
  local ref="$1" archive ref_dir ref_root
  if [[ "$ref" == "$RESOLVED_SHA" ]]; then
    printf '%s\n' "$TARGET_CLIENT_HASH"
    return 0
  fi
  archive="$WORK/client-ref-$ref.tar.gz"
  ref_dir="$WORK/client-ref-$ref"
  mkdir -p "$ref_dir"
  if ! curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$ref" -o "$archive"; then
    return 1
  fi
  if ! tar -xzf "$archive" -C "$ref_dir"; then
    return 1
  fi
  ref_root="$(find "$ref_dir" -maxdepth 1 -mindepth 1 -type d -name 'RDP-*' | head -n1)"
  [[ -n "$ref_root" ]] || return 1
  client_bundle_hash "$ref_root"
}

add_candidate_client_ref "$CONFIG_CLIENT_REF"
IFS=',' read -r -a CONFIG_COMPATIBLE_ARRAY <<< "$CONFIG_COMPATIBLE_REFS"
for ref in "${CONFIG_COMPATIBLE_ARRAY[@]:-}"; do
  add_candidate_client_ref "$ref"
done
for ref in $TELEMETRY_CLIENT_REFS; do
  add_candidate_client_ref "$ref"
done
add_candidate_client_ref "$PREVIOUS_REF"
add_candidate_client_ref "$RESOLVED_SHA"

for ref in "${CANDIDATE_CLIENT_REFS[@]}"; do
  if CLIENT_HASH="$(client_bundle_hash_for_ref "$ref")"; then
    if [[ "$CLIENT_HASH" == "$TARGET_CLIENT_HASH" ]]; then
      add_compatible_client_ref "$ref"
    fi
  else
    echo "WARNING: unable to inspect client bundle ref $ref" >&2
  fi
done

add_compatible_client_ref "$RESOLVED_SHA"

NEW_CLIENT_REF="$RESOLVED_SHA"
for ref in "$CONFIG_CLIENT_REF" $TELEMETRY_CLIENT_REFS "$PREVIOUS_REF"; do
  for compatible in "${COMPATIBLE_CLIENT_REFS[@]}"; do
    if [[ "${ref,,}" == "$compatible" ]]; then
      NEW_CLIENT_REF="$compatible"
      break 2
    fi
  done
done

COMPATIBLE_CLIENT_CSV="$(IFS=,; echo "${COMPATIBLE_CLIENT_REFS[*]}")"
echo "SERVER_REF=$RESOLVED_SHA"
echo "CLIENT_REF=$NEW_CLIENT_REF"
echo "CLIENT_COMPATIBLE_REFS=$COMPATIBLE_CLIENT_CSV"

BAKUNITY_TRANSPORT_CLIENT_REF="$NEW_CLIENT_REF"   bash "$ROOT/scripts/build-native-transport-windows.sh"

install -d -m 0700 "$BACKUP"
for path in \
  /opt/hermes-rdp \
  /etc/hermes-rdp/config.json \
  /etc/hermes-rdp/sshd_config \
  /etc/systemd/system/hermes-rdp.service \
  /etc/systemd/system/hermes-rdp-sshd.service \
  /etc/systemd/system/bakunity-rdp-default.service \
  /usr/local/sbin/hermes-rdp-cert-package \
  /usr/local/sbin/hermes-rdp-device-cert-package \
  /usr/local/sbin/hermes-rdp-cert-renew \
  /usr/local/sbin/hermes-rdp-cert-state-refresh \
  /usr/local/sbin/bakunity-rdp-mesh-key \
  /etc/sudoers.d/bakunity-rdp-mesh-key \
  /usr/local/bin/hermes-rdpctl \
  /usr/local/bin/bakunity-rdpctl \
  /etc/sudoers.d/hermes-rdp-cert-package \
  /etc/hermes-rdp/trusted-rdp-cert-state.json; do
  [[ -e "$path" ]] && cp -a --parents "$path" "$BACKUP/"
done

install -d -m 0700 "$BACKUP/var/lib/hermes-rdp"
python3 - "$DB" "$BACKUP/var/lib/hermes-rdp/state.sqlite3" <<'PY'
import sqlite3
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
destination_path = Path(sys.argv[2])
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
destination = sqlite3.connect(destination_path)
try:
    source.backup(destination)
    row = destination.execute("PRAGMA quick_check").fetchone()
    if not row or row[0] != "ok":
        raise RuntimeError(f"backup quick_check failed: {row!r}")
finally:
    destination.close()
    source.close()
PY
chmod 0600 "$BACKUP/var/lib/hermes-rdp/state.sqlite3"

python3 - \
  "$BACKUP/update-metadata.json" \
  "$REF" \
  "$RESOLVED_SHA" \
  "$PREVIOUS_REF" \
  "$PREVIOUS_CLIENT_REF" \
  "$NEW_CLIENT_REF" \
  "$COMPATIBLE_CLIENT_CSV" \
  "$DB_UID" \
  "$DB_GID" \
  "$DB_MODE" <<'PY'
import json
import sys
from pathlib import Path

(
    path,
    requested_ref,
    resolved_sha,
    previous_ref,
    previous_client_ref,
    new_client_ref,
    compatible_client_refs,
    db_uid,
    db_gid,
    db_mode,
) = sys.argv[1:]
Path(path).write_text(
    json.dumps(
        {
            "requested_ref": requested_ref,
            "resolved_sha": resolved_sha,
            "previous_repository_ref": previous_ref,
            "previous_client_repository_ref": previous_client_ref,
            "client_repository_ref": new_client_ref,
            "client_compatible_refs": [
                ref for ref in compatible_client_refs.split(",") if ref
            ],
            "database_uid": int(db_uid),
            "database_gid": int(db_gid),
            "database_mode": db_mode,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
chmod 0600 "$BACKUP/update-metadata.json"
ln -sfn "$BACKUP" /var/backups/hermes-rdp/latest-update

ROLLBACK_ARMED=1

rm -rf /opt/hermes-rdp/source
install -d -m 0755 /opt/hermes-rdp/source
cp -a "$ROOT"/. /opt/hermes-rdp/source/
chown -R root:root /opt/hermes-rdp/source
test -f /opt/hermes-rdp/source/scripts/setup-native-transport.sh
test -f /opt/hermes-rdp/source/native-transport/go.mod

rm -rf /opt/hermes-rdp/app/hermes_rdp
cp -a "$ROOT/server/hermes_rdp" /opt/hermes-rdp/app/hermes_rdp
chown -R root:root /opt/hermes-rdp/app

cat > /usr/local/bin/hermes-rdpctl <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/hermes-rdp/app
exec /usr/bin/python3 -m hermes_rdp.cli "$@"
EOF
chmod 0755 /usr/local/bin/hermes-rdpctl

cat > /usr/local/bin/bakunity-rdpctl <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/hermes-rdp/app
exec /usr/bin/python3 -m hermes_rdp.cli "$@"
EOF
chmod 0755 /usr/local/bin/bakunity-rdpctl

install -m 0644 \
  "$ROOT/server/systemd/hermes-rdp.service" \
  /etc/systemd/system/hermes-rdp.service
install -m 0644 \
  "$ROOT/server/systemd/hermes-rdp-sshd.service" \
  /etc/systemd/system/hermes-rdp-sshd.service
install -m 0644 \
  "$ROOT/server/systemd/bakunity-rdp-default.service" \
  /etc/systemd/system/bakunity-rdp-default.service

install -m 0755 \
  "$ROOT/server/bin/bakunity-rdp-mesh-key.sh" \
  /usr/local/sbin/bakunity-rdp-mesh-key
install -m 0440 \
  "$ROOT/server/sudoers/bakunity-rdp-mesh-key" \
  /etc/sudoers.d/bakunity-rdp-mesh-key
visudo -cf /etc/sudoers.d/bakunity-rdp-mesh-key >/dev/null

if ((TRUSTED_CERT_ENABLED == 1)); then
  install -m 0755 \
    "$ROOT/server/bin/hermes-rdp-cert-package.sh" \
    /usr/local/sbin/hermes-rdp-cert-package
  install -m 0755 \
    "$ROOT/server/bin/hermes-rdp-device-cert-package.sh" \
    /usr/local/sbin/hermes-rdp-device-cert-package
  install -m 0755 \
    "$ROOT/server/bin/hermes-rdp-cert-renew.sh" \
    /usr/local/sbin/hermes-rdp-cert-renew
  install -m 0755 \
    "$ROOT/server/bin/hermes-rdp-cert-state-refresh.sh" \
    /usr/local/sbin/hermes-rdp-cert-state-refresh
  install -m 0440 \
    "$ROOT/server/sudoers/hermes-rdp-cert-package" \
    /etc/sudoers.d/hermes-rdp-cert-package
  visudo -cf /etc/sudoers.d/hermes-rdp-cert-package >/dev/null
  /usr/local/sbin/hermes-rdp-cert-state-refresh >/dev/null
  test -s /etc/hermes-rdp/trusted-rdp-cert-state.json
fi

python3 - "$REF" "$RESOLVED_SHA" "$NEW_CLIENT_REF" "$COMPATIBLE_CLIENT_CSV" <<'PY'
import json
import sys
from pathlib import Path

requested_ref, resolved_sha, client_ref, compatible_refs = sys.argv[1:]
path = Path("/etc/hermes-rdp/config.json")
data = json.loads(path.read_text(encoding="utf-8"))
data["client_installer_url"] = (
    "https://raw.githubusercontent.com/bakunity/RDP/"
    f"{client_ref}/scripts/install-client.ps1"
)
data["repository_ref"] = resolved_sha
data["repository_requested_ref"] = requested_ref
data["client_repository_ref"] = client_ref
data["client_compatible_refs"] = [
    ref for ref in compatible_refs.split(",") if ref
]
path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
chmod 0640 /etc/hermes-rdp/config.json
chown root:hermes-rdp /etc/hermes-rdp/config.json

ufw allow "3389/tcp" comment 'Bakunity RDP default device' >/dev/null || true

PYTHONPATH=/opt/hermes-rdp/app \
  python3 -m compileall -q /opt/hermes-rdp/app/hermes_rdp
/usr/sbin/sshd -t -f /etc/hermes-rdp/sshd_config

systemctl daemon-reload
systemctl restart hermes-rdp-sshd.service hermes-rdp.service
if ((DEFAULT_RDP_WAS_ACTIVE == 1)); then
  systemctl restart bakunity-rdp-default.service
  systemctl is-active --quiet bakunity-rdp-default.service
fi
systemctl is-active --quiet hermes-rdp-sshd.service
systemctl is-active --quiet hermes-rdp.service
wait_health
PYTHONPATH=/opt/hermes-rdp/app python3 -m hermes_rdp.cli doctor >/dev/null
/usr/local/bin/hermes-rdpctl doctor >/dev/null
/usr/local/bin/bakunity-rdpctl doctor >/dev/null
python3 - "$DB" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    row = connection.execute("PRAGMA quick_check").fetchone()
finally:
    connection.close()
if not row or row[0] != "ok":
    raise SystemExit(f"database quick_check failed: {row!r}")
PY

ROLLBACK_ARMED=0
echo "Updated to $RESOLVED_SHA. Backup: $BACKUP"
echo "UPDATE=PASS"
