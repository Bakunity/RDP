#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo '== Bash syntax =='
find scripts server/bin -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n

echo '== Python compile =='
python3 -m compileall -q server/hermes_rdp tests scripts/check-public-examples.py

echo '== Python tests =='
PYTHONPATH=server python3 -m unittest discover -s tests -v

echo '== Public example privacy =='
python3 scripts/check-public-examples.py

echo '== Installer archive reference =='
python3 -c "from pathlib import Path; t=Path('scripts/install-server.sh').read_text(); assert 'archive/refs/heads/\$REF.tar.gz' not in t, 'installer treats release refs as branches'; assert 'https://codeload.github.com/\$REPO/tar.gz/\$REF' in t, 'missing branch/tag compatible archive endpoint'; print('installer-archive-ref=OK')"

echo '== Trusted RDP certificate lifecycle =='
python3 - <<'PY'
from pathlib import Path

setup = Path('scripts/setup-trusted-rdp-cert.sh').read_text(encoding='utf-8')
renew = Path('server/bin/hermes-rdp-cert-renew.sh').read_text(encoding='utf-8')
service = Path('server/systemd/hermes-rdp-cert-renew.service').read_text(encoding='utf-8')
timer = Path('server/systemd/hermes-rdp-cert-renew.timer').read_text(encoding='utf-8')
installer = Path('scripts/install-server.sh').read_text(encoding='utf-8')
uninstaller = Path('scripts/uninstall-server.sh').read_text(encoding='utf-8')

for marker in [
    '--staging',
    '--standalone',
    '--preferred-profile shortlived',
    '--ip-address "$HOST"',
    "ufw allow 80/tcp comment 'Hermes ACME HTTP-01'",
]:
    if marker not in setup:
        raise SystemExit(f'setup script missing required marker: {marker}')
if 'CERT_PUB' not in setup or 'KEY_PUB' not in setup:
    raise SystemExit('setup script lost certificate/private-key match validation')

if '--cert-name "$CERT_NAME"' in renew:
    raise SystemExit('renew wrapper still limits renewal to the legacy public-IP lineage')

for marker in [
    '/usr/bin/flock -w 300',
    '"$CERTBOT" renew',
    '--quiet',
    '--non-interactive',
]:
    if marker not in renew:
        raise SystemExit(f'renew wrapper missing required marker: {marker}')

if 'ExecStart=/usr/local/sbin/hermes-rdp-cert-renew' not in service:
    raise SystemExit('renewal service does not use Hermes wrapper')
if 'ConditionPathExists=/etc/hermes-rdp/trusted-rdp-cert.enabled' not in service:
    raise SystemExit('renewal service lacks Hermes enable marker')

for marker in [
    'OnCalendar=*-*-* 00,12:00:00',
    'RandomizedDelaySec=1h',
    'Persistent=true',
    'Unit=hermes-rdp-cert-renew.service',
]:
    if marker not in timer:
        raise SystemExit(f'renewal timer missing required marker: {marker}')

for marker in [
    '--trusted-rdp-cert',
    'TRUSTED_RDP_CERT=1',
    'setup-trusted-rdp-cert.sh',
    'trusted_rdp_certificate=',
]:
    if marker not in installer:
        raise SystemExit(f'installer missing trusted certificate wiring: {marker}')

for marker in [
    'hermes-rdp-cert-renew.timer',
    'hermes-rdp-cert-renew.service',
    '/usr/local/sbin/hermes-rdp-cert-renew',
    'ACME certificate lineage were preserved',
]:
    if marker not in uninstaller:
        raise SystemExit(f'uninstaller missing trusted certificate lifecycle handling: {marker}')

if '/etc/letsencrypt' in '\n'.join(
    line for line in uninstaller.splitlines() if line.lstrip().startswith('rm ')
):
    raise SystemExit('uninstaller must not delete the ACME certificate lineage')

print('trusted-rdp-cert-lifecycle=OK')
PY

echo '== Release metadata =='
python3 - <<'PY'
from __future__ import annotations

import re
from pathlib import Path


def read_project_version(path: Path) -> str:
    in_project = False
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if line.startswith('[') and line.endswith(']'):
            in_project = line == '[project]'
            continue
        if not in_project:
            continue
        match = re.fullmatch(r'version\s*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    raise SystemExit(f'project.version not found in {path}')


root = Path.cwd()
version = (root / 'VERSION').read_text(encoding='utf-8').strip()
if not re.fullmatch(r'\d+\.\d+\.\d+', version):
    raise SystemExit(f'invalid VERSION: {version!r}')

init_text = (root / 'server/hermes_rdp/__init__.py').read_text(encoding='utf-8')
match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
if not match or match.group(1) != version:
    raise SystemExit('__version__ does not match VERSION')

package_version = read_project_version(root / 'server/pyproject.toml')
if package_version != version:
    raise SystemExit('pyproject version does not match VERSION')

notes = root / 'docs/releases' / f'v{version}.md'
if not notes.is_file():
    raise SystemExit(f'missing release notes: {notes}')

changelog = (root / 'CHANGELOG.md').read_text(encoding='utf-8')
if f'## [{version}]' not in changelog:
    raise SystemExit('CHANGELOG has no current version section')

required_link = f'https://github.com/bakunity/RDP/releases/tag/v{version}'
for relative in ['README.md', 'CHANGELOG.md', f'docs/releases/v{version}.md']:
    text = (root / relative).read_text(encoding='utf-8')
    if required_link not in text:
        raise SystemExit(f'{relative} does not contain current release link')

print(f'version={version}')
print(f'release_notes={notes}')
PY

echo '== Text control characters =='
python3 - <<'PY'
from pathlib import Path

root = Path.cwd()
allowed = {9, 10, 13}
failed = []
for path in root.rglob('*'):
    if not path.is_file() or '.git' in path.parts:
        continue
    if path.suffix.lower() not in {'.md', '.py', '.ps1', '.sh', '.toml', '.yml', '.yaml', '.json'}:
        continue
    raw = path.read_bytes()
    for index, value in enumerate(raw):
        if value < 32 and value not in allowed:
            failed.append(f'{path}:{index}:0x{value:02x}')
            break
if failed:
    raise SystemExit('control characters found:\n' + '\n'.join(failed))
print('control-characters=OK')
PY

echo '== PowerShell encoding =='
python3 - <<'PY'
from pathlib import Path

failed = []
for path in Path('.').rglob('*.ps1'):
    raw = path.read_bytes()
    if not raw.startswith(b'\xef\xbb\xbf'):
        failed.append(str(path))
if failed:
    raise SystemExit('PowerShell files must use UTF-8 BOM:\n' + '\n'.join(failed))
print('powershell-utf8-bom=OK')
PY

echo 'ALL CHECKS PASSED'
