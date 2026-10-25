# Разработка Bakunity RDP

Документ предназначен для будущих разработчиков и ревьюеров. Перед изменением кода прочитай [ARCHITECTURE.md](ARCHITECTURE.md) и [SECURITY.md](SECURITY.md).

## Принципы проекта

1. **Только сервер особенный.** Первый и последующие Windows-клиенты используют одинаковый код.
2. **FRPS работает постоянно.** ON/OFF управляет FRPC выбранного устройства.
3. **Один Telegram dashboard.** Интерфейс редактирует одно сообщение вместо создания ленты.
4. **Устройство изолировано логически.** Device ID, API token, port, telemetry и command sequence персональны.
5. **Установка должна оставаться простой.** Сервер и Windows разворачиваются готовыми скриптами.
6. **Секреты не попадают в Git.** Ни реальные tokens, ни приватные ключи, ни device configs.
7. **Изменения должны иметь откат.** Установщики и updater сохраняют backup.

## Структура репозитория

```text
RDP/
├── client/
│   └── HermesRdpAgent.ps1       Windows agent
├── server/
│   ├── hermes_rdp/
│   │   ├── api.py               HTTPS API
│   │   ├── bot.py               Telegram UI
│   │   ├── cli.py               hermes-rdpctl
│   │   ├── config.py            server configuration
│   │   ├── db.py                SQLite registry
│   │   └── service.py           process lifecycle
│   ├── systemd/                 production units
│   └── pyproject.toml
├── scripts/
│   ├── install-server.sh
│   ├── install-client.ps1
│   ├── update-server.sh
│   ├── update-client.ps1
│   ├── uninstall-server.sh
│   ├── uninstall-client.ps1
│   └── check-release.sh
├── tests/
├── docs/
├── .github/workflows/
├── VERSION
└── CHANGELOG.md
```

## Локальная среда Linux

Требуется Python 3.11+.

```bash
git clone https://github.com/bakunity/RDP.git
cd RDP
```

Запустить тесты:

```bash
PYTHONPATH=server python3 -m unittest discover -s tests -v
```

Проверить компиляцию:

```bash
python3 -m compileall -q server/hermes_rdp
```

Проверить Bash:

```bash
find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

Полная проверка:

```bash
bash scripts/check-release.sh
```

## Проверка PowerShell

PowerShell-файлы должны корректно разбираться Windows PowerShell 5.1. Файлы с русским текстом хранятся в UTF-8 BOM.

```powershell
$Failed=$false; Get-ChildItem -Recurse -Filter *.ps1 | ForEach-Object { $t=$null; $e=$null; [void][Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$t,[ref]$e); if($e.Count){$Failed=$true; $e | ForEach-Object { Write-Error "$($_.Extent.StartLineNumber): $($_.Message)" }}}; if($Failed){exit 1}
```

CI выполняет эту проверку на Windows runner.

## Локальный запуск server code

Production config по умолчанию читается из:

```text
/etc/hermes-rdp/config.json
```

Для локального тестирования удобнее создавать временную конфигурацию и вызывать отдельные классы в тестах, а не запускать Telegram bot с реальным token.

`Registry` принимает путь к SQLite и диапазон портов, поэтому легко тестируется через `TemporaryDirectory`.

## Где менять функциональность

### Добавить telemetry metric

1. собрать поле в `client/HermesRdpAgent.ps1`;
2. оставить поле JSON-совместимым;
3. добавить безопасный fallback в `bot.py`;
4. обновить `docs/API.md`;
5. проверить старый payload без нового поля;
6. обновить release notes.

### Добавить Telegram action

1. добавить callback button в `bot.py`;
2. при необходимости расширить `Registry.queue_command`;
3. добавить обработку в `Invoke-CommandAction` Windows agent;
4. использовать sequence и command-result;
5. не выполнять привилегированную операцию непосредственно из текста пользователя;
6. добавить тесты.

### Добавить server CLI command

1. расширить parser в `cli.py`;
2. использовать публичный метод `Registry`;
3. печатать однозначный exit code;
4. добавить команду в `COMMANDS.md` и `OPERATIONS.md`.

### Изменить pairing

Pairing — security-sensitive path. Обязательно проверить:

- code TTL;
- one-time consumption;
- port allocation under concurrent requests;
- отсутствие token в server logs;
- совместимость Windows PowerShell 5.1;
- TLS fingerprint verification до отправки code.

## Database migrations

В v1 schema создаётся через `CREATE TABLE IF NOT EXISTS`. При добавлении столбца нельзя просто изменить CREATE TABLE для существующих баз.

Для будущих изменений:

1. добавить явную версию schema в `settings`;
2. выполнять миграции транзакционно;
3. создавать backup SQLite перед migration;
4. поддерживать обновление минимум с последнего стабильного релиза;
5. добавить тест миграции из предыдущей schema.

## API compatibility

- существующие поля нельзя переименовывать внутри `/v1`;
- новые поля должны быть необязательными;
- старый client должен работать с новым server;
- новый client должен проверять server version, если требует новую возможность;
- breaking change требует `/v2`.

## Telegram UX

Dashboard ограничен Telegram message limit. Device view обрезается до 4000 символов.

Правила:

- не отправлять новое сообщение при каждом refresh;
- callback data держать коротким;
- не помещать secrets в message;
- при удалённом dashboard уметь создать новый;
- при неизвестном device возвращаться на home;
- LIVE loop не должен падать из-за одного битого telemetry field.

## Windows compatibility

Минимальная целевая среда — Windows PowerShell 5.1.

Не использовать без fallback:

- синтаксис только PowerShell 7;
- API, отсутствующие в Windows 10/11 штатно;
- UTF-8 без BOM для файлов с non-ASCII source text;
- интерактивный desktop для task, работающей от `SYSTEM`.

## Security checklist для PR

- [ ] secrets не логируются;
- [ ] новые файлы secrets получают ограниченный ACL/mode;
- [ ] входные строки ограничены по длине;
- [ ] SQL использует parameters;
- [ ] Telegram actor проверяется;
- [ ] API endpoint проверяет Bearer token;
- [ ] TLS verification не ослаблена;
- [ ] install/update сохраняет backup;
- [ ] нет команды, выключающей FRPS для одного клиента;
- [ ] документация обновлена.

## Git workflow

1. создать ветку от `main`;
2. внести одну логически завершённую группу изменений;
3. выполнить `bash scripts/check-release.sh`;
4. открыть PR;
5. дождаться Linux и Windows CI;
6. не merge при красном CI;
7. для релиза обновить `VERSION`, `CHANGELOG.md` и `docs/releases/vX.Y.Z.md`.

## Версионирование

- PATCH — исправления без изменения контракта;
- MINOR — обратно совместимые возможности;
- MAJOR — несовместимые изменения API, config или deployment contract.

Источник версии должен совпадать в:

- `VERSION`;
- `server/hermes_rdp/__init__.py`;
- `server/pyproject.toml`;
- release notes filename.

Эта согласованность проверяется тестом и release workflow.

## Что не делать

- не создавать отдельный код для «основного ПК»;
- не хранить список устройств в FRPS config вручную;
- не использовать Telegram как транспорт telemetry;
- не открывать дополнительный входящий порт на Windows;
- не хранить plaintext device token в SQLite;
- не добавлять бинарники FRP в Git;
- не менять рабочий endpoint пользователя без явной миграции.
