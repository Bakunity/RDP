# Процесс релиза

Bakunity RDP использует Semantic Versioning и автоматическую публикацию GitHub Release после merge релизного PR в `main`.

## Источники версии

Версия должна совпадать в четырёх местах:

```text
VERSION
server/hermes_rdp/__init__.py
server/pyproject.toml
docs/releases/vX.Y.Z.md
```

API `/healthz` берёт version из `hermes_rdp.__version__`, поэтому отдельную строку в `api.py` менять не нужно.

## Что обновлять в релизном PR

1. `VERSION`;
2. `server/hermes_rdp/__init__.py`;
3. `server/pyproject.toml`;
4. `CHANGELOG.md`;
5. concise `docs/releases/vX.Y.Z.md`;
6. full `docs/releases/history/vX.Y.Z-full.md`;
7. `docs/releases/UNRELEASED.md` — начать следующий cycle после сохранения full history;
8. README/site, если изменились stable version, команды или требования;
9. migration/security docs, если затронут deployment contract.

## Локальная проверка

```bash
bash scripts/check-release.sh
```

Проверяются:

- Bash syntax;
- Python compile;
- unit tests;
- public example privacy;
- trusted RDP certificate lifecycle static invariants;
- согласованность version files;
- наличие release notes;
- отсутствие управляющих символов;
- корректность ссылок на текущий release tag в основных документах.

PowerShell parse дополнительно выполняется Windows job в GitHub Actions.

## Pull request

Релизный PR должен содержать:

- краткое резюме;
- breaking changes;
- migration plan;
- security impact;
- результаты Linux и Windows CI;
- план отката;
- ссылку на release notes и full engineering history.

Merge запрещён при красном CI.

## Автоматическая публикация

Workflow `.github/workflows/release.yml` запускается после релизных изменений в `main`.

Ключевая гарантия: новый tag ставится на **exact validated workflow `HEAD`**, а не на commit, который последним менял `VERSION`.

Алгоритм:

1. fetch release history;
2. запускает full release validation;
3. читает `VERSION` и формирует `vX.Y.Z`;
4. использует текущий validated `HEAD` как release SHA;
5. создаёт immutable tag, только если его ещё нет;
6. создаёт или синхронизирует GitHub Release body из `docs/releases/vX.Y.Z.md`;
7. при изменении старого `docs/releases/v*.md` синхронизирует matching historical Release body;
8. существующие tags никогда не перемещаются.

Подробный `history/vX.Y.Z-full.md` не публикуется как Release body: GitHub Release намеренно остаётся коротким.

GitHub Release:

```text
https://github.com/bakunity/RDP/releases/tag/vX.Y.Z
```

Последний релиз:

```text
https://github.com/bakunity/RDP/releases/latest
```

## Ручная публикация

Используется только если automatic workflow недоступен.

Сначала убедитесь, что текущий checkout — exact validated release head.

```bash
VERSION="$(tr -d '\r\n' < VERSION)"
TAG="v$VERSION"
git tag -a "$TAG" -m "Bakunity RDP $TAG"
git push origin "$TAG"
gh release create "$TAG" --title "Bakunity RDP $TAG" --notes-file "docs/releases/$TAG.md" --verify-tag
```

## Stable install URLs

Server:

```text
https://raw.githubusercontent.com/bakunity/RDP/vX.Y.Z/scripts/install-server.sh
```

Windows:

```text
https://raw.githubusercontent.com/bakunity/RDP/vX.Y.Z/scripts/install-client.ps1
```

Update scripts:

```text
https://raw.githubusercontent.com/bakunity/RDP/vX.Y.Z/scripts/update-server.sh
https://raw.githubusercontent.com/bakunity/RDP/vX.Y.Z/scripts/update-client.ps1
```

Release commands в README и release notes должны использовать tag, а не `main`.

## Rollback релиза

Не перемещайте опубликованный tag на другой commit.

При критической ошибке:

1. пометьте release как problematic в notes;
2. подготовьте исправление;
3. выпустите PATCH version;
4. при необходимости документируйте rollback на предыдущий tag;
5. не переписывайте историю стабильного релиза.

## Checklist

- [ ] version согласована;
- [ ] changelog обновлён;
- [ ] concise release notes созданы;
- [ ] full engineering history создана;
- [ ] `UNRELEASED` переведён на следующий cycle;
- [ ] README/site и команды используют новый tag;
- [ ] Python tests PASS;
- [ ] Python compile PASS;
- [ ] Bash syntax PASS;
- [ ] public privacy scan PASS;
- [ ] Windows PowerShell 5.1 parse PASS;
- [ ] migration/security impact проверен;
- [ ] backup/rollback описаны;
- [ ] PR merge выполнен только после final exact-head CI;
- [ ] tag создан на exact validated release head;
- [ ] GitHub Release опубликован;
- [ ] release links открываются;
