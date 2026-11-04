#!/usr/bin/env bash
set -Eeuo pipefail

REPO="bakunity/RDP"
REF="${HERMES_RDP_REF:-main}"
CLAIM_TIMEOUT="${HERMES_CLAIM_TIMEOUT:-600}"
WORK_DIR="$(mktemp -d)"
APT_LOG="$WORK_DIR/apt-update.log"
TG_TOKEN=""

cleanup() {
  unset TG_TOKEN || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

say() { printf '%s\n' "$*"; }
pass() { printf '✓ %s\n' "$*"; }
warn() { printf '⚠ %s\n' "$*" >&2; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

if [[ ${EUID} -ne 0 ]]; then
  die "Запустите установщик через sudo: curl .../scripts/install.sh | sudo bash"
fi
if [[ ! -r /dev/tty ]]; then
  die "Нужен интерактивный терминал (/dev/tty) для безопасного ввода Telegram bot token."
fi
if [[ ! -r /etc/os-release ]]; then
  die "Не удалось определить Linux distribution: /etc/os-release отсутствует."
fi
# shellcheck disable=SC1091
source /etc/os-release
OS_ID="${ID:-unknown}"
OS_NAME="${PRETTY_NAME:-$OS_ID}"
CODENAME="${VERSION_CODENAME:-}"
case "$OS_ID" in
  debian|ubuntu) ;;
  *) die "Неподдерживаемая ОС: $OS_NAME. Нужен Debian или Ubuntu." ;;
esac
command -v systemctl >/dev/null 2>&1 || die "systemd/systemctl не найден."
command -v apt-get >/dev/null 2>&1 || die "apt-get не найден."

say "=== HERMES RDP INSTALLER ==="
pass "OS: $OS_NAME"
pass "Architecture: $(dpkg --print-architecture 2>/dev/null || uname -m)"
pass "root/sudo"

normalize_simple_apt_entries_in_file() {
  local file="$1" tmp
  tmp="$(mktemp "$WORK_DIR/apt-normalize.XXXXXX")"
  awk '
    {
      raw[NR]=$0
      line=$0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line ~ /^(deb|deb-src)[[:space:]]+/ && line !~ /\[/ && line !~ /#/) {
        n=split(line, part, /[[:space:]]+/)
        if (n >= 4) {
          key=part[1] SUBSEP part[2] SUBSEP part[3]
          if (!(key in first)) {
            first[key]=NR
            line_key[NR]=key
            type[key]=part[1]
            uri[key]=part[2]
            suite[key]=part[3]
          } else {
            skip[NR]=1
          }
          for (i=4; i<=n; i++) {
            component_key=key SUBSEP part[i]
            if (!(component_key in component_seen)) {
              component_seen[component_key]=1
              components[key]=(components[key] == "" ? part[i] : components[key] " " part[i])
            }
          }
          next
        }
      }
    }
    END {
      for (i=1; i<=NR; i++) {
        if (skip[i]) continue
        if (i in line_key) {
          key=line_key[i]
          print type[key] " " uri[key] " " suite[key] " " components[key]
        } else {
          print raw[i]
        }
      }
    }
  ' "$file" >"$tmp"
  if cmp -s "$file" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  cat "$tmp" >"$file"
  rm -f "$tmp"
  return 0
}

repair_duplicate_apt_warnings() {
  grep -q 'is configured multiple times' "$APT_LOG" || return 1

  local stamp backup file changed=0
  local -a files=()
  [[ -f /etc/apt/sources.list ]] && files+=(/etc/apt/sources.list)
  for file in /etc/apt/sources.list.d/*.list; do
    [[ -f "$file" ]] && files+=("$file")
  done
  ((${#files[@]} > 0)) || return 1

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup="/var/backups/hermes-rdp/apt-sources-dedupe-$stamp"
  install -d -m 0700 "$backup"

  for file in "${files[@]}"; do
    cp -a --parents "$file" "$backup/"
    if normalize_simple_apt_entries_in_file "$file"; then
      changed=1
    fi
  done

  if ((changed == 0)); then
    rm -rf "$backup"
    return 1
  fi

  if apt-get update -qq >"$APT_LOG" 2>&1 && ! grep -q 'is configured multiple times' "$APT_LOG"; then
    pass "APT repositories: normalized overlapping deb/deb-src entries"
    say "  backup: $backup"
    return 0
  fi

  warn "Нормализация duplicate APT entries не прошла проверку; source-файлы восстановлены."
  cp -a "$backup/etc/apt/." /etc/apt/
  apt-get update -qq >"$APT_LOG" 2>&1 || true
  return 1
}

repair_known_debian_archive_source() {
  [[ "$OS_ID" == "debian" && -n "$CODENAME" ]] || return 1
  command -v curl >/dev/null 2>&1 || return 1
  curl -fsSL --max-time 12 "https://deb.debian.org/debian/dists/$CODENAME/Release" -o /dev/null || return 1

  local -a files=()
  while IFS= read -r file; do
    [[ -n "$file" ]] && files+=("$file")
  done < <(
    grep -RIlE 'https?://archive\.debian\.org/debian(-security)?' \
      /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null || true
  )
  ((${#files[@]} > 0)) || return 1

  local stamp backup file
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup="/var/backups/hermes-rdp/apt-sources-$stamp"
  install -d -m 0700 "$backup"
  for file in "${files[@]}"; do
    cp -a --parents "$file" "$backup/"
    sed -i -E \
      -e 's#https?://archive\.debian\.org/debian-security#https://security.debian.org/debian-security#g' \
      -e 's#https?://archive\.debian\.org/debian#https://deb.debian.org/debian#g' \
      "$file"
    normalize_simple_apt_entries_in_file "$file" || true
  done

  if apt-get update -qq >"$APT_LOG" 2>&1 && ! grep -q 'is configured multiple times' "$APT_LOG"; then
    pass "APT repositories: repaired stale Debian archive source"
    say "  backup: $backup"
    return 0
  fi

  warn "Автоматическое исправление APT не помогло; исходные source-файлы восстановлены."
  cp -a "$backup/etc/apt/." /etc/apt/
  return 1
}

export DEBIAN_FRONTEND=noninteractive
if apt-get update -qq >"$APT_LOG" 2>&1; then
  if grep -q 'is configured multiple times' "$APT_LOG"; then
    repair_duplicate_apt_warnings || pass "APT repositories (duplicate warning left unchanged)"
  else
    pass "APT repositories"
  fi
else
  warn "APT repositories не проходят проверку."
  if ! repair_known_debian_archive_source; then
    say >&2
    say "Последние строки apt-get update:" >&2
    tail -n 12 "$APT_LOG" >&2 || true
    say >&2
    die "Hermes ещё не устанавливался. Исправьте APT repositories и повторите эту же команду."
  fi
fi

apt-get install -y -qq ca-certificates curl openssl python3 >/dev/null
pass "Bootstrap dependencies"

is_global_ipv4() {
  python3 - "$1" <<'PY' >/dev/null 2>&1
import ipaddress
import sys
try:
    value = ipaddress.ip_address(sys.argv[1].strip())
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if value.version == 4 and value.is_global else 1)
PY
}

detect_public_ipv4() {
  local candidate="" iface=""
  iface="$(ip -4 route show default 2>/dev/null | awk '/default/ {for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}' || true)"
  if [[ -n "$iface" ]]; then
    candidate="$(ip -4 addr show dev "$iface" scope global 2>/dev/null | awk '/inet / {sub(/\/.*/, "", $2); print $2; exit}' || true)"
    if [[ -n "$candidate" ]] && is_global_ipv4 "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  local endpoint
  for endpoint in \
    "https://api.ipify.org" \
    "https://ipv4.icanhazip.com" \
    "https://ifconfig.me/ip"; do
    candidate="$(curl -4 -fsSL --max-time 10 "$endpoint" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -n "$candidate" ]] && is_global_ipv4 "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PUBLIC_IPV4="$(detect_public_ipv4 || true)"
[[ -n "$PUBLIC_IPV4" ]] || die "Не удалось автоматически определить глобальный public IPv4. Для нестандартной сети используйте advanced install-server.sh."
pass "Public IPv4: $PUBLIC_IPV4"

telegram_call() {
  local method="$1"
  local payload="${2:-}"
  [[ -n "$payload" ]] || payload='{}'
  python3 - "$method" "$payload" 3<<<"$TG_TOKEN" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

method = sys.argv[1]
payload = json.loads(sys.argv[2])
token = os.fdopen(3, "r", encoding="utf-8").read().strip()
request = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/{method}",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
    print(f"Telegram API request failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
if not body.get("ok"):
    print(body.get("description", "Telegram API error"), file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(body.get("result"), ensure_ascii=False))
PY
}

read_masked_telegram_token() {
  local char
  TG_TOKEN=""
  printf 'Telegram bot token: ' >/dev/tty
  while IFS= read -r -s -n1 char </dev/tty; do
    if [[ -z "$char" ]]; then
      printf '\n' >/dev/tty
      return 0
    fi
    case "$char" in
      $'\177'|$'\b')
        if [[ -n "$TG_TOKEN" ]]; then
          TG_TOKEN="${TG_TOKEN%?}"
          printf '\b \b' >/dev/tty
        fi
        ;;
      *)
        TG_TOKEN+="$char"
        printf '*' >/dev/tty
        ;;
    esac
  done
  printf '\n' >/dev/tty
  return 1
}

say
BOT_INFO=""
for attempt in 1 2 3; do
  read_masked_telegram_token || die "Не удалось прочитать Telegram bot token из /dev/tty."
  if [[ -z "$TG_TOKEN" ]]; then
    warn "Telegram bot token пустой. Попробуйте ещё раз ($attempt/3)."
    continue
  fi
  if BOT_INFO="$(telegram_call getMe '{}')"; then
    break
  fi
  TG_TOKEN=""
  warn "Telegram bot token не прошёл проверку getMe. Проверьте токен и повторите ($attempt/3)."
done
[[ -n "$BOT_INFO" ]] || die "Telegram bot token не удалось подтвердить после 3 попыток."

BOT_USERNAME="$(printf '%s' "$BOT_INFO" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("username", ""))')"
[[ -n "$BOT_USERNAME" ]] || die "Telegram getMe не вернул username бота."
pass "Telegram bot: @$BOT_USERNAME"

WEBHOOK_INFO="$(telegram_call getWebhookInfo '{}')" || die "Не удалось проверить Telegram webhook."
WEBHOOK_URL="$(printf '%s' "$WEBHOOK_INFO" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("url", ""))')"
[[ -z "$WEBHOOK_URL" ]] || die "У @${BOT_USERNAME} уже настроен webhook. Используйте отдельного бота Hermes или сначала освободите этого бота."
pass "Telegram webhook: free"

BASE_UPDATES="$(telegram_call getUpdates '{"timeout":0,"limit":100,"allowed_updates":["message"]}')" || die "Telegram getUpdates недоступен."
OFFSET="$(printf '%s' "$BASE_UPDATES" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(max([int(x["update_id"]) for x in rows], default=-1)+1)')"
CLAIM_CODE="$(python3 -c 'import secrets; print(f"{secrets.randbelow(100000000):08d}")')"

say
say "Привязка владельца Telegram"
say "1. Откройте @$BOT_USERNAME в Telegram."
say "2. Отправьте боту ровно эту команду:"
say
say "   /claim $CLAIM_CODE"
say
say "Ожидаю подтверждение (до $((CLAIM_TIMEOUT / 60)) мин)..."

OWNER_ID="$(python3 - "$OFFSET" "$CLAIM_CODE" "$CLAIM_TIMEOUT" 3<<<"$TG_TOKEN" <<'PY'
import json
import os
import sys
import time
import urllib.request

offset = int(sys.argv[1])
claim = sys.argv[2]
deadline = time.monotonic() + int(sys.argv[3])
token = os.fdopen(3, "r", encoding="utf-8").read().strip()
base = f"https://api.telegram.org/bot{token}"

def call(method, payload):
    req = urllib.request.Request(
        f"{base}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        body = json.loads(response.read().decode())
    if not body.get("ok"):
        raise RuntimeError(body.get("description", "Telegram API error"))
    return body.get("result")

while time.monotonic() < deadline:
    timeout = min(20, max(1, int(deadline - time.monotonic())))
    rows = call("getUpdates", {
        "offset": offset,
        "timeout": timeout,
        "limit": 100,
        "allowed_updates": ["message"],
    })
    for update in rows:
        offset = int(update["update_id"]) + 1
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        actor = message.get("from") or {}
        text = str(message.get("text") or "").strip()
        if chat.get("type") != "private":
            continue
        if str(chat.get("id", "")) != str(actor.get("id", "")):
            continue
        if text != f"/claim {claim}":
            continue
        owner = str(actor["id"])
        call("sendMessage", {
            "chat_id": owner,
            "text": "✅ Hermes RDP: владелец подтверждён. Установка на сервере продолжается.",
        })
        call("getUpdates", {"offset": offset, "timeout": 0, "limit": 1})
        print(owner)
        raise SystemExit(0)
print("Telegram owner claim timed out", file=sys.stderr)
raise SystemExit(1)
PY
)" || die "Telegram owner claim не подтверждён. Запустите установщик повторно и используйте новый код."
[[ "$OWNER_ID" =~ ^-?[0-9]+$ ]] || die "Telegram owner ID имеет неожиданный формат."
pass "Telegram owner confirmed"
unset CLAIM_CODE

SOURCE_ARCHIVE="$WORK_DIR/source.tar.gz"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$SOURCE_ARCHIVE"
tar -xzf "$SOURCE_ARCHIVE" -C "$WORK_DIR"
SOURCE_ROOT="$(find "$WORK_DIR" -maxdepth 1 -mindepth 1 -type d -name 'RDP-*' | head -n1)"
[[ -n "$SOURCE_ROOT" && -x "$SOURCE_ROOT/scripts/install-server.sh" ]] || die "Не удалось получить Hermes source ref $REF."
pass "Hermes source: $REF"

say
say "Устанавливаю Hermes RDP..."
"$SOURCE_ROOT/scripts/install-server.sh" \
  --host "$PUBLIC_IPV4" \
  --telegram-token "$TG_TOKEN" \
  --telegram-chat-id "$OWNER_ID"

pass "Hermes core installed"

TRUSTED_STATUS="unavailable"
if [[ -x "$SOURCE_ROOT/scripts/setup-trusted-rdp-cert.sh" ]]; then
  say
  say "Проверяю trusted RDP certificate lifecycle..."
  if "$SOURCE_ROOT/scripts/setup-trusted-rdp-cert.sh" --host "$PUBLIC_IPV4"; then
    TRUSTED_STATUS="active"
    pass "Trusted RDP certificate lifecycle"
  else
    warn "Trusted RDP certificate сейчас недоступен. Основной Hermes уже установлен и работает."
    warn "Обычно причина — закрытый/занятый TCP 80 или внешний firewall. После исправления TLS можно включить отдельно."
  fi
fi

say
say "=== HERMES RDP READY ==="
say "Server: $PUBLIC_IPV4"
say "Telegram: @$BOT_USERNAME"
say "Owner: confirmed"
say "Transport: OpenSSH"
say "Trusted RDP TLS: $TRUSTED_STATUS"
say
say "Откройте Telegram и отправьте /start боту @$BOT_USERNAME."
