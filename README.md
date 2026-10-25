# Bakunity RDP

<p align="center">
  <strong>Self-hosted multi-PC RDP gateway через один публичный Linux-сервер с управлением из Telegram.</strong>
</p>

<p align="center">
  <a href="https://github.com/bakunity/RDP/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/bakunity/RDP?display_name=tag"></a>
  <a href="https://github.com/bakunity/RDP/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/bakunity/RDP/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
  <a href="docs/ARCHITECTURE.md"><img alt="OpenSSH" src="https://img.shields.io/badge/transport-OpenSSH-2ea44f"></a>
  <a href="docs/INSTALL_WINDOWS.md"><img alt="Windows" src="https://img.shields.io/badge/client-Windows%2010%2F11%20%7C%20Server%202019-blue"></a>
  <a href="docs/INSTALL_SERVER.md"><img alt="Linux" src="https://img.shields.io/badge/server-Debian%20%7C%20Ubuntu-orange"></a>
</p>

<p align="center">
  <a href="https://rdp.bakunity.com/">Сайт</a> ·
  <a href="https://github.com/bakunity/RDP/releases/latest">Релизы</a> ·
  <a href="docs/INDEX.md">Документация</a> ·
  <a href="docs/SECURITY.md">Безопасность</a> ·
  <a href="docs/VALIDATED_SCENARIOS.md">Проверенные сценарии</a>
</p>

Bakunity RDP публикует RDP нескольких Windows-компьютеров через один Linux-сервер с публичным IP или DNS. Каждый Windows-ПК сам поднимает исходящий reverse OpenSSH-туннель, получает постоянный внешний endpoint и управляется из одного Telegram dashboard.

На домашнем или офисном роутере Windows-ПК не требуется пробрасывать входящий RDP-порт: соединение к Hermes инициирует сам Windows-клиент.

> **Главный принцип проекта:** все Windows-компьютеры равноправны. Для каждого используется один installer и один Hermes Agent. Специальным узлом является только Linux-сервер Hermes.

> **Stable release:** [Bakunity RDP v1.3.0](https://github.com/bakunity/RDP/releases/tag/v1.3.0). Для production используйте release tag или другой заранее проверенный immutable ref, а не изменяемый `main`.

## Что умеет Bakunity RDP

- несколько независимых Windows-ПК через один сервер;
- постоянные endpoints вида `SERVER:53389`, `SERVER:53390`, `SERVER:53391`;
- стандартный Microsoft Remote Desktop без отдельного RDP-клиента Hermes;
- системный Microsoft OpenSSH вместо стороннего tunnel binary;
- отдельный Ed25519 keypair, API-token и порт для каждого устройства;
- Telegram `ON`, `OFF`, `RESTART`, Repair, удаление и LIVE-состояние каждого ПК;
- автоматический reconnect после сетевых сбоев и перезагрузок;
- Windows 10/11 и Windows Server support;
- transactional server/client update с backup и automatic rollback;
- Repair существующего клиента без повторного pairing и смены identity/порта;
- работа без Defender exclusions и без отключения Microsoft Defender;
- автоматический trusted certificate lifecycle для Windows RDP listener: server renewal, Windows rotation и lifecycle integration.

## Схема

```text
Windows ПК ─┐
Windows ПК ─┼─ reverse OpenSSH :7000 ─> Hermes Linux server ─> SERVER:RDP_PORT
Windows ПК ─┘                                  │
                                              ├─ HTTPS API :7443
                                              ├─ SQLite registry
                                              └─ Telegram control

Microsoft Remote Desktop
  └─ SERVER:RDP_PORT ─> reverse SSH ─> Windows :3389
```

Каждый device key ограничен сервером только своим endpoint через `permitlisten`. Административный SSH `:22` и Hermes tunnel sshd `:7000` независимы.

## Trusted RDP certificate

Опциональный `--trusted-rdp-cert` включает отдельный certificate lifecycle для **Windows RDP listener**:

```text
Let’s Encrypt public-IP certificate
        ↓
Hermes renewal timer + non-secret state
        ↓
authenticated Windows LocalSystem rotation worker
        ↓
CUSTOM certificate binding RDP-Tcp
        ↓
Microsoft Remote Desktop без прежнего self-signed warning
```

Это отдельная trust boundary от HTTPS API certificate pinning. Сертификат API защищает control plane; сертификат Windows RDP listener видит Microsoft Remote Desktop.

После включения server-side lifecycle normal Fresh Install, Update и Repair автоматически управляют rotation companion. Uninstall удаляет обе Hermes Scheduled Tasks и локальный runtime. Certificate work остаётся вне performance-sensitive 3-second Agent loop.

Требования: глобально маршрутизируемый public IPv4, доступный TCP `80` для ACME HTTP-01 и доступ к Let’s Encrypt.

Подробнее: [INSTALL_SERVER](docs/INSTALL_SERVER.md), [INSTALL_WINDOWS](docs/INSTALL_WINDOWS.md), [SECURITY](docs/SECURITY.md).

## Telegram dashboard

Для нового компьютера используется **➕ ДОБАВИТЬ ПК**. Pairing-код одноразовый; если он истёк или уже использован, **🔁 НОВЫЙ КОД** выдаёт новый код и обновлённую installer command.

Карточка существующего ПК разделяет heartbeat, desired access, SSH transport, endpoint и telemetry. Основные действия:

```text
🟢 ON / 🔴 OFF          включить или отключить RDP access
🔄 RESTART              пересоздать Hermes SSH transport
🛠 ВОССТАНОВИТЬ КЛИЕНТ  восстановить existing Windows client
🗑 DELETE                отозвать устройство и освободить endpoint
```

Fresh pairing и Repair намеренно разделены. Repair не создаёт новый Device ID и не выполняет скрытый re-pair/rekey.

## Порты по умолчанию

| Назначение | Порт |
|---|---:|
| Administrative SSH | `22/tcp` |
| Hermes OpenSSH tunnel | `7000/tcp` |
| HTTPS API | `7443/tcp` |
| RDP endpoints | `53389–53420/tcp` |
| ACME HTTP-01 | `80/tcp` только для trusted certificate lifecycle |

Стандартный RDP-пул содержит 32 endpoint и расширяется параметрами server installer.

## Требования

**Server:** Debian/Ubuntu, Python 3.11+, systemd, OpenSSH Server, root/sudo, публичный IPv4 или DNS и доступ к GitHub/Telegram API.

**Windows:** Windows 10/11 Pro, Enterprise или Education x64 либо поддерживаемый Windows Server, Windows PowerShell 5.1+, локальный Administrator и Microsoft OpenSSH Client.

Windows Home не является штатным RDP host и не поддерживается.

## Быстрый старт v1.3.0

### 1. Установить сервер

Базовый OpenSSH gateway:

```bash
curl -fsSL https://raw.githubusercontent.com/bakunity/RDP/v1.3.0/scripts/install-server.sh -o /tmp/install-hermes-rdp.sh
read -rsp 'Telegram bot token: ' TG_TOKEN; echo
sudo env HERMES_RDP_REF=v1.3.0 bash /tmp/install-hermes-rdp.sh \
  --host SERVER_IP_OR_DOMAIN \
  --telegram-token "$TG_TOKEN" \
  --telegram-chat-id TELEGRAM_USER_ID
unset TG_TOKEN
rm -f /tmp/install-hermes-rdp.sh
```

С trusted public-IP RDP certificate lifecycle добавьте `--trusted-rdp-cert` и используйте public IPv4 в `--host`:

```bash
sudo env HERMES_RDP_REF=v1.3.0 bash /tmp/install-hermes-rdp.sh \
  --host PUBLIC_IPV4 \
  --telegram-token "$TG_TOKEN" \
  --telegram-chat-id TELEGRAM_USER_ID \
  --trusted-rdp-cert
```

Проверка:

```bash
sudo hermes-rdpctl doctor
sudo systemctl is-active hermes-rdp-sshd.service hermes-rdp.service
```

При trusted lifecycle дополнительно:

```bash
sudo systemctl is-active hermes-rdp-cert-renew.timer
```

### 2. Добавить Windows-ПК

1. Отправьте `/start` Telegram-боту.
2. Нажмите **➕ ДОБАВИТЬ ПК**.
3. Откройте PowerShell от имени администратора.
4. Скопируйте команду из Telegram целиком.
5. Введите понятное название компьютера.
6. Дождитесь `=== ГОТОВО ===`.

Если trusted lifecycle включён на сервере, Fresh Install сам создаст certificate rotation companion и применит trusted CUSTOM listener certificate.

### 3. Подключиться

```powershell
mstsc.exe /v:SERVER_IP_OR_DOMAIN:53389
```

Первый свободный endpoint обычно начинается с `53389`, следующий получает `53390` и так далее.

## Обновление

Server:

```bash
curl -fsSL https://raw.githubusercontent.com/bakunity/RDP/v1.3.0/scripts/update-server.sh -o /tmp/update-hermes-rdp.sh
sudo env HERMES_RDP_REF=v1.3.0 bash /tmp/update-hermes-rdp.sh
rm -f /tmp/update-hermes-rdp.sh
```

Windows:

```powershell
$u='https://raw.githubusercontent.com/bakunity/RDP/v1.3.0/scripts/update-client.ps1'
$s=(irm $u).TrimStart([char]0xFEFF)
& ([scriptblock]::Create($s)) -RepositoryRef 'v1.3.0'
```

Windows Update разрешает основной Agent и certificate lifecycle setup в один immutable SHA. Certificate sub-operation завершается до финального `UPDATE=PASS`; failure участвует в transactional rollback boundary.

## Repair и Uninstall

Для уже зарегистрированного компьютера используйте **🛠 ВОССТАНОВИТЬ КЛИЕНТ**. Repair сохраняет Device ID, API-token, Ed25519 keypair, `known_hosts` и назначенный RDP-порт, а при включённом trusted lifecycle также восстанавливает certificate rotation companion.

Потеря обязательной local identity останавливает Repair вместо скрытого re-pair/rekey.

Normal uninstall останавливает и unregister-ит основной Agent и certificate rotation task, завершает Hermes runtime и архивирует активный `C:\ProgramData\HermesRDP`. После локального uninstall удалите устройство в Telegram для server-side revoke и освобождения порта.

## Безопасность

- HTTPS API использует TLS и certificate fingerprint pinning;
- SSH host key получается через уже pinned API и закрепляется в отдельном `known_hosts`;
- `StrictHostKeyChecking=yes`;
- каждый Windows-ПК имеет отдельный Ed25519 keypair;
- private SSH key остаётся на Windows;
- `permitlisten` ограничивает device key одним назначенным endpoint;
- у каждого устройства отдельный API-token, сервер хранит только hash;
- Telegram control ограничен заданным owner user/chat ID;
- admin SSH `:22` и Hermes tunnel sshd `:7000` разделены;
- Hermes не добавляет Defender exclusions;
- trusted RDP lifecycle не смешивает API TLS и Windows RDP listener TLS.

**RDP boundary:** Hermes защищает регистрацию, control plane, tunnel и, при включённом trusted lifecycle, TLS identity listener. Windows credentials, NLA, обновления ОС и Windows authorization остаются отдельной границей безопасности.

Подробнее: [docs/SECURITY.md](docs/SECURITY.md).

## Что проверено

В реальной эксплуатации подтверждены multi-device endpoints, внешний RDP, Windows/Linux reboot recovery, `OFF/ON/RESTART`, Win10 x64 из 32-bit PowerShell через Sysnative, Windows Server 2019, Defender coexistence, delete/revocation/port reuse, transactional update/rollback и Repair/rollback.

Для v1.3.0 также live-приняты: публично доверенный RDP certificate, rollback/reapply, automatic drift recovery, LocalSystem rotation worker, certificate lifecycle в Update/Repair, чистый Fresh Install, внешний trusted RDP и normal Uninstall.

Отдельно отложено только наблюдение следующей **естественной** certificate renewal; форсировать production issuance ради него не требуется.

Полный acceptance без secret material: [docs/VALIDATED_SCENARIOS.md](docs/VALIDATED_SCENARIOS.md).

## Основные команды

Hermes server:

```bash
sudo hermes-rdpctl doctor
sudo hermes-rdpctl devices list
sudo hermes-rdpctl pair create --name 'Office-PC'
sudo hermes-rdpctl devices rename DEVICE_ID 'New name'
sudo hermes-rdpctl devices delete DEVICE_ID
sudo systemctl status hermes-rdp-sshd.service hermes-rdp.service --no-pager
```

Windows diagnostics:

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Agent'
Get-ScheduledTask -TaskName 'Bakunity RDP Certificate Rotation' -ErrorAction SilentlyContinue
Get-Content 'C:\ProgramData\HermesRDP\agent.log' -Tail 100
Get-Process ssh -ErrorAction SilentlyContinue
```

## Документация

| Документ | Для чего |
|---|---|
| [Быстрый старт](docs/QUICKSTART.md) | Развернуть Hermes и подключить первый ПК |
| [Установка сервера](docs/INSTALL_SERVER.md) | Server setup, порты и trusted certificate option |
| [Установка Windows](docs/INSTALL_WINDOWS.md) | Fresh pairing, compatibility и certificate lifecycle |
| [Архитектура](docs/ARCHITECTURE.md) | Компоненты, data flow и TLS boundaries |
| [API](docs/API.md) | Pairing, telemetry и command contracts |
| [Эксплуатация](docs/OPERATIONS.md) | Backup, update, Repair, renewal и uninstall |
| [Диагностика](docs/TROUBLESHOOTING.md) | Поиск проблем по симптомам |
| [Безопасность](docs/SECURITY.md) | TLS, identity, SSH restrictions и RDP boundary |
| [Проверенные сценарии](docs/VALIDATED_SCENARIOS.md) | Реально пройденный acceptance |
| [Тестирование от А до Я](docs/TESTING_A_TO_Z.md) | Regression-bounded проверка |
| [Разработка](docs/DEVELOPMENT.md) | Структура проекта и developer rules |
| [Релизный процесс](docs/RELEASE.md) | Versioning, CI и GitHub Release |

Полный индекс: [docs/INDEX.md](docs/INDEX.md).

## Релизы

- [Последний релиз](https://github.com/bakunity/RDP/releases/latest)
- [Bakunity RDP v1.3.0](https://github.com/bakunity/RDP/releases/tag/v1.3.0)
- [Release notes v1.3.0](docs/releases/v1.3.0.md)
- [Полная история v1.3.0](docs/releases/history/v1.3.0-full.md)
- [Предыдущий v1.2.1](https://github.com/bakunity/RDP/releases/tag/v1.2.1)
- [Следующий релиз — rolling ledger](docs/releases/UNRELEASED.md)
- [История изменений](CHANGELOG.md)

Для production используйте конкретный release tag или другой заранее проверенный immutable ref. `main` предназначен для дальнейшей разработки.

## Лицензия

[MIT](LICENSE).
