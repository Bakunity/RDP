# Contributing to Bakunity RDP

Спасибо за вклад. Bakunity RDP управляет удалённым доступом и хранит чувствительные credentials, поэтому изменения должны проходить review и CI.

## Перед началом

Прочитай:

- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/DEVELOPMENT.md)
- [Security](docs/SECURITY.md)
- [API contract](docs/API.md)

## Основные правила

1. Сервер Bakunity — единственный специальный узел.
2. Все Windows-компьютеры используют один client/agent.
3. ON/OFF отдельного устройства не должен останавливать общий FRPS.
4. Secrets, private keys и реальные configs нельзя добавлять в Git.
5. Любое изменение deployment contract требует migration docs.
6. Любое изменение API требует обновления `docs/API.md`.
7. PowerShell должен разбираться Windows PowerShell 5.1.
8. Файлы `.ps1` с non-ASCII text должны сохраняться в UTF-8 BOM.

## Workflow

```bash
git switch main
git pull --ff-only
git switch -c feat/short-description
```

После изменений:

```bash
bash scripts/check-release.sh
```

Создай PR с:

- целью изменения;
- кратким описанием архитектуры;
- результатами tests;
- security impact;
- migration/rollback;
- screenshots Telegram UX, если менялся bot.

## Tests

Linux:

```bash
PYTHONPATH=server python3 -m unittest discover -s tests -v
python3 -m compileall -q server/hermes_rdp
find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

Windows PowerShell parse выполняется CI. Локальная команда есть в [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Требования к коду

### Python

- type hints для новых public functions;
- parameterized SQL;
- ограничение входных строк;
- no secrets in logs;
- backward-compatible API fields;
- tests для Registry/API logic.

### PowerShell

- совместимость с 5.1;
- `$ErrorActionPreference = 'Stop'` для installers/updaters;
- проверка admin context;
- backup до замены файла;
- syntax parse до restart task;
- secrets с protected ACL;
- никаких зависимостей от interactive desktop для task `SYSTEM`.

### Bash

- `set -Eeuo pipefail`;
- quoted variables;
- SHA-256 verification downloads;
- backup до mutation;
- systemd/config validation до restart;
- понятные exit codes.

## Release changes

Для релиза обнови:

- `VERSION`;
- `server/hermes_rdp/__init__.py`;
- `server/pyproject.toml`;
- `CHANGELOG.md`;
- `docs/releases/vX.Y.Z.md`.

Подробности: [docs/RELEASE.md](docs/RELEASE.md).

## Запрещено коммитить

- Telegram bot token;
- FRP token;
- `device.json`;
- `frpc.toml` с действующими credentials;
- TLS private keys;
- SQLite production database;
- server backups;
- реальные pair codes;
- RDP passwords;
- бинарники FRP.

## Security reports

Не публикуй рабочий exploit или действующие credentials в обычном issue. Следуй [SECURITY.md](SECURITY.md).
