# Changelog

Все заметные изменения проекта фиксируются здесь. Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии следуют Semantic Versioning.

## [Unreleased]

## [1.3.0] — 2026-08-14

Релиз: https://github.com/bakunity/RDP/releases/tag/v1.3.0

Функциональный релиз trusted public-IP certificate lifecycle для Windows RDP listener с автоматической ротацией и интеграцией в обычный Windows lifecycle.

### Добавлено

- опциональная server-side настройка Let’s Encrypt short-lived certificate для публичного IPv4;
- Hermes-owned certificate renewal service/timer и non-secret state/status;
- authenticated certificate package delivery зарегистрированному Windows device;
- отдельный LocalSystem certificate-rotation worker вне основного Agent loop;
- автоматическое управление trusted CUSTOM RDP listener certificate в Fresh Install, Update и Repair.

### Исправлено

- корректный rollback между Windows default self-signed listener и explicit CUSTOM binding;
- LocalSystem task validation через SID вместо локализованного имени `SYSTEM`;
- upgrade path global mutex ACL между SYSTEM worker и Administrator setup;
- automatic recovery после controlled local listener drift.

### Lifecycle

- transactional Update включает certificate sub-operation до `UPDATE=PASS`;
- Repair восстанавливает certificate rotation companion без re-pair/rekey и смены identity/порта;
- normal Uninstall удаляет основной Agent и certificate-rotation runtime;
- server install/update/uninstall управляют certificate helpers/state без удаления ACME lineage.

### Проверено

- production public-IP issuance, chain/key validation и renewal smoke;
- внешний Microsoft Remote Desktop с trusted certificate без self-signed warning;
- automatic drift recovery;
- live Update/Repair с сохранением device identity/keys/known_hosts/RDP port;
- чистый Windows 10 Pro / PowerShell 5.1 / Defender-enabled Fresh Install и normal Uninstall;
- Linux full release checks и Windows PowerShell 5.1 validation на промежуточных accepted heads.

### Документация и release process

- core docs, README и public site синхронизированы с accepted certificate lifecycle;
- public Release notes и full engineering history разделены;
- release workflow tags exact validated HEAD и синхронизирует versioned Release bodies без переписывания tags;
- public example privacy guard блокирует случайную публикацию production IP.

### Совместимость

- breaking changes относительно `v1.2.1` нет;
- Windows PowerShell 5.1, Win10 x64/x86 Sysnative path, Windows Server и Defender coexistence сохраняются;
- trusted RDP certificate lifecycle опционален и требует public IPv4 + TCP 80 для ACME HTTP-01.

## [1.2.1] — 2026-08-13

Релиз: https://github.com/bakunity/RDP/releases/tag/v1.2.1

Hotfix release packaging после некорректной точки тега `v1.2.0`.

### Исправлено

- `v1.2.1` публикует полный согласованный release tree вместо первого commit, где менялся только `VERSION`;
- в release tag входят согласованные package version metadata, release notes и полный product README;
- README снова оформлен как полноценная страница Bakunity RDP с badges, архитектурой, quick start, update/repair и security sections.

### Совместимость

- runtime-функциональность соответствует уже live-accepted stabilization baseline;
- breaking changes относительно `v1.1.0` не вводятся;
- для новых install/update рекомендуется `v1.2.1`, а не неполный `v1.2.0` tag.

## [1.2.0] — 2026-08-13

Релиз: https://github.com/bakunity/RDP/releases/tag/v1.2.0

Стабилизационный релиз после перехода на OpenSSH.

### Добавлено

- отдельный Repair существующего Windows-клиента;
- Telegram-действия `ВОССТАНОВИТЬ КЛИЕНТ` и `НОВЫЙ КОД`;
- transactional update/rollback для server и Windows client;
- Windows Server support и x86 PowerShell compatibility.

### Исправлено

- soak-time control-plane deadlocks и stale command state;
- dashboard state refresh и mobile control layout;
- Windows installer startup readiness;
- server updater backup/rollback consistency;
- Windows updater rollback/recovery;
- performance regression в ordinary telemetry path.

### Проверено

- несколько Windows-устройств одновременно;
- Windows и Linux reboot recovery;
- device failure isolation;
- device delete и безопасное повторное использование endpoint;
- Repair success/rollback paths;
- pairing retry UX.

### Документация и сайт

- public docs синхронизированы с live-accepted `v1.2.0` behavior;
- validated scenarios и release draft обновлены по фактической evidence.

## [1.1.0] — 2026-08-06

Релиз: https://github.com/bakunity/RDP/releases/tag/v1.1.0

Крупный релиз: транспорт Bakunity RDP переведён с FRP на системный OpenSSH.

### Добавлено

- отдельный изолированный `sshd` на порту `7000/tcp`;
- индивидуальный Ed25519-ключ и постоянный RDP-порт для каждого ПК;
- динамический `AuthorizedKeysCommand` с `permitlisten` только на назначенный порт;
- закрепление SSH host key через уже закреплённый HTTPS API;
- автоматическое восстановление reverse SSH-туннеля после обрыва или перезагрузки;
- атомарный pairing, отзыв SSH-ключа и повторное использование освобождённых портов.

### Изменено

- Windows использует встроенные `ssh.exe` и `ssh-keygen.exe`;
- Telegram ON/OFF/RESTART управляет OpenSSH-туннелем;
- OFF и DELETE закрывают активный listener на сервере;
- миграция с `v1.0.x` выполняется явно через `--migrate`.

### Удалено

- `frps`, `frpc.exe`, загрузка стороннего FRP-архива и Defender exclusions.

### Безопасность

- tunnel-user не получает shell, PTY, SFTP, agent forwarding или произвольные порты;
- private key остаётся только на Windows-ПК;
- удаление устройства отзывает API-token и SSH public key.

## [1.0.7] — 2026-08-06

Hotfix HTTPS certificate pinning в Windows PowerShell 5.1.

### Исправлено

- PowerShell scriptblock удалён из `ServerCertificateCustomValidationCallback`;
- проверка SHA-256 fingerprint выполняется статическим C# callback без зависимости от PowerShell runspace;
- сетевой запрос больше не завершается общей `HttpRequestException` при корректно доступном сервере;
- fingerprint pinning сохранён: неверный сертификат по-прежнему отклоняется;
- добавлен Windows runtime test с реальным самоподписанным сертификатом;
- добавлены Python regression tests, запрещающие возврат PowerShell callback.

### Совместимость

- API, SQLite registry, pairing contract, FRP и стандартные порты не изменены;
- `install-client.ps1` остаётся совместимым с Windows PowerShell 5.1.

## [1.0.6] — 2026-08-06

Hotfix запуска Windows-установщика через Telegram-команду в PowerShell 5.1.

### Исправлено

- перед `ScriptBlock.Create()` удаляется декодированный UTF-8 BOM (`U+FEFF`);
- начальный `param(...)` установщика снова корректно распознаётся при загрузке через `irm`;
- Telegram-команда остаётся компактной, многострочной и копируется одним нажатием;
- regression test проверяет наличие BOM-нормализации и запрещает возврат прямого `Create((irm $u))`.

### Совместимость

- сам `install-client.ps1` остаётся в UTF-8 BOM для корректной работы русского текста в Windows PowerShell 5.1;
- API, SQLite registry, pairing contract, FRP и стандартные порты не изменены.

## [1.0.5] — 2026-08-06

UX-патч компактной команды Telegram и исправление обновления активного сервиса.

### Изменено

- команда Windows-установщика остаётся одним копируемым блоком, но разбита на короткие строки через PowerShell splatting;
- убрана чрезмерная ширина Telegram code block;
- команда не использует хрупкие символы продолжения строки PowerShell;
- повторный запуск серверного установщика явно перезапускает уже активные `frps` и `hermes-rdp`;
- `update-server.sh` корректно загружает как ветки, так и release-теги;
- добавлены regression tests Telegram-разметки и поведения обновления.

### Совместимость

- pairing contract, API, SQLite, FRP-протокол и Windows agent не изменены;
- обновление затрагивает только отображение Telegram-панели;
- стандартные порты не изменены.

## [1.0.4] — 2026-08-06

UX-патч Telegram-экрана добавления Windows-ПК.

### Изменено

- команда установки выводится единым моноширинным блоком Telegram;
- всю PowerShell-команду можно скопировать одним нажатием;
- включён HTML parse mode для отправки и редактирования панели;
- команда HTML-экранируется, поэтому `&`, ссылки и другие специальные символы не ломают сообщение;
- добавлены regression tests формата команды и Telegram payload.

### Совместимость

- API, SQLite registry, pairing contract, FRP и Windows agent не изменены;
- обновление затрагивает только отображение Telegram-панели;
- стандартные порты не изменены.

## [1.0.3] — 2026-08-06

Hotfix чистой серверной установки после проверки на отдельном Debian-сервере.

### Исправлено

- установщик больше не запускает `sed` по отсутствующему `/etc/frp/frps.toml`;
- чтение legacy FRP token выполняется только при наличии старого конфигурационного файла;
- чистая установка больше не завершается с `exit=2` до создания systemd-служб;
- добавлен regression test структуры clean-install ветки.

### Совместимость

- публичные команды и стандартные порты не изменены;
- исправление затрагивает только ветку чистой серверной установки.

## [1.0.2] — 2026-08-06

Hotfix загрузки FRP Windows-клиентом при ложном срабатывании Microsoft Defender.

### Исправлено

- добавлена явная диагностика Defender quarantine по событиям 1116/1117;
- FRP-загрузка выполняется до расходования pairing-кода;
- cleanup временных файлов не перекрывает исходную ошибку установки;
- при обнаружении quarantine показывается понятное сообщение без автоматического ослабления Defender.

## [1.0.1] — 2026-08-05

Hotfix bootstrap Windows-установщика.

### Исправлено

- Telegram-команда загружает PowerShell-установщик без сохранения во временный файл;
- сохранена проверка TLS fingerprint;
- исправлена совместимость PowerShell 5.1.

## [1.0.0] — 2026-08-05

Первый публичный релиз Bakunity RDP.

### Добавлено

- Linux controller и FRP gateway;
- Windows agent и FRPC client;
- Telegram dashboard;
- SQLite registry;
- HTTPS API с TLS pinning;
- multi-PC support;
- диагностика и release automation.
