#!/usr/bin/env bash
set -Eeuo pipefail

REPO="Bakunity/RDP"
CONFIG="/etc/hermes-rdp/config.json"
ENABLED="/etc/hermes-rdp/autodeploy.enabled"
STATUS="/var/lib/hermes-rdp/autodeploy-status.json"
LOCK="/run/hermes-rdp-autodeploy.lock"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

exec 9>"$LOCK"
if ! flock -n 9; then
  exit 0
fi

write_status() {
  local state="$1"
  local ref="${2:-}"
  local target="${3:-}"
  local detail="${4:-}"
  install -d -m 0755 /var/lib/hermes-rdp
  python3 - "$STATUS" "$state" "$ref" "$target" "$detail" <<'PY'
import json
import sys
import time
from pathlib import Path

path, state, ref, target, detail = sys.argv[1:]
Path(path).write_text(
    json.dumps(
        {
            "state": state,
            "ref": ref,
            "target_sha": target,
            "detail": detail,
            "updated_at": int(time.time()),
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
  chmod 0644 "$STATUS"
}

[[ -e "$ENABLED" ]] || {
  write_status "disabled" "" "" "marker is absent"
  exit 0
}
[[ -s "$CONFIG" ]] || {
  write_status "error" "" "" "config is missing"
  exit 1
}

read -r TRACK_REF CURRENT_SHA < <(
  python3 - "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    str(data.get("repository_requested_ref") or "").strip(),
    str(data.get("repository_ref") or "").strip().lower(),
)
PY
)

if [[ -z "$TRACK_REF" ]]; then
  write_status "error" "" "$CURRENT_SHA" "repository_requested_ref is empty"
  exit 1
fi
if [[ "$TRACK_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
  write_status "paused" "$TRACK_REF" "$CURRENT_SHA" "immutable ref is not tracked"
  exit 0
fi
if [[ "$TRACK_REF" == "main" ]]; then
  write_status "paused" "$TRACK_REF" "$CURRENT_SHA" "main uses GitHub Production Ops"
  exit 0
fi

TARGET_SHA="$(
  git ls-remote     "https://github.com/${REPO}.git"     "refs/heads/${TRACK_REF}" |
    awk 'NR == 1 {print tolower($1)}'
)"
if ! [[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  write_status "error" "$TRACK_REF" "$CURRENT_SHA" "unable to resolve branch"
  exit 1
fi

if [[ "$TARGET_SHA" == "$CURRENT_SHA" ]]; then
  write_status "current" "$TRACK_REF" "$TARGET_SHA" "already deployed"
  exit 0
fi

CI_RESULT="$(
  curl -fsSL     -H 'Accept: application/vnd.github+json'     "https://api.github.com/repos/${REPO}/actions/runs?head_sha=${TARGET_SHA}&per_page=20" |
  python3 - "$TARGET_SHA" <<'PY'
import json
import sys

target = sys.argv[1].lower()
payload = json.load(sys.stdin)
runs = [
    run
    for run in payload.get("workflow_runs", [])
    if str(run.get("head_sha") or "").lower() == target
    and str(run.get("name") or "") == "CI"
]
if any(run.get("conclusion") == "success" for run in runs):
    print("success")
elif any(run.get("status") in {"queued", "in_progress", "pending", "waiting", "requested"} for run in runs):
    print("pending")
elif runs:
    print("failed")
else:
    print("missing")
PY
)"

case "$CI_RESULT" in
  success)
    ;;
  pending|missing)
    write_status "waiting-ci" "$TRACK_REF" "$TARGET_SHA" "CI=${CI_RESULT}"
    exit 0
    ;;
  *)
    write_status "blocked" "$TRACK_REF" "$TARGET_SHA" "CI=${CI_RESULT}"
    exit 0
    ;;
esac

write_status "deploying" "$TRACK_REF" "$TARGET_SHA" "CI=success"

UPDATE="$WORK/update-server.sh"
curl -fsSL   "https://raw.githubusercontent.com/${REPO}/${TARGET_SHA}/scripts/update-server.sh"   -o "$UPDATE"
chmod 0700 "$UPDATE"

if env   BAKUNITY_RDP_REF="$TARGET_SHA"   BAKUNITY_RDP_TRACK_REF="$TRACK_REF"   BAKUNITY_RDP_AUTODEPLOY=1   bash "$UPDATE"; then
  /usr/local/bin/bakunity-rdpctl doctor >/dev/null
  write_status "deployed" "$TRACK_REF" "$TARGET_SHA" "doctor=pass"
  echo "AUTODEPLOY=PASS ref=$TRACK_REF sha=$TARGET_SHA"
else
  rc=$?
  write_status "failed" "$TRACK_REF" "$TARGET_SHA" "update rc=$rc"
  echo "AUTODEPLOY=FAIL ref=$TRACK_REF sha=$TARGET_SHA rc=$rc" >&2
  exit "$rc"
fi
