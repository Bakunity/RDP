# Архитектура Bakunity RDP

## Общая схема

```text
Remote RDP client
        |
        | TCP SERVER:RDP_PORT
        v
Linux listener created by dedicated sshd
        |
        | reverse forwarding
        v
Windows 127.0.0.1:3389
```

Windows всегда инициирует исходящее SSH-соединение. Проброс портов на домашнем или офисном роутере Windows-ПК не требуется.

## Сервер

### `hermes-rdp-sshd.service`

Отдельный экземпляр OpenSSH на `7000/tcp`. Он не заменяет административный SSH сервера и использует собственные config, pid file и host key.

Ограничения tunnel-user:

- только public-key authentication;
- нет shell, PTY и SFTP;
- нет X11 и agent forwarding;
- нет local forwarding;
- remote forwarding ограничен назначенным endpoint;
- `AuthorizedKeysCommand` получает актуальный ключ из SQLite;
- `permitlisten` разрешает только конкретный RDP-порт.

### `hermes-rdp.service`

Запускает:

- HTTPS API;
- Telegram controller;
- SQLite registry;
- pairing;
- telemetry и heartbeat;
- очередь команд устройствам;
- authenticated certificate status/package endpoints для зарегистрированных устройств, когда trusted RDP lifecycle включён.

### SQLite

Хранит:

- устройства и назначенные порты;
- хэши API-token;
- SSH public keys;
- pairing-коды;
- команды;
- настройки Telegram;
- последнюю телеметрию.

## Windows

`HermesRdpAgent.ps1` работает через Scheduled Task от имени `SYSTEM` и поддерживает:

- `ssh.exe -N -R`;
- reconnect и backoff;
- heartbeat и telemetry;
- команды `ON`, `OFF`, `RESTART`;
- проверку endpoint status.

Приватный Ed25519-ключ остаётся в `C:\ProgramData\HermesRDP` с ACL только для `SYSTEM` и Administrators.

Certificate lifecycle вынесен из performance-sensitive Agent loop в отдельный низкочастотный worker `HermesRdpCertRotation.ps1`, также запускаемый Scheduled Task от LocalSystem. Он сначала получает только non-secret desired certificate state и скачивает PFX package только при изменении thumbprint или локальном listener drift.

## Две независимые TLS-границы

Bakunity использует два разных сертификатных контура, и их нельзя смешивать.

### HTTPS API trust

1. Пользователь получает API fingerprint через доверенный канал установки.
2. Installer закрепляет SHA-256 сертификата HTTPS API.
3. Через закреплённый API клиент получает SSH host key.
4. SSH использует отдельный `known_hosts` и `StrictHostKeyChecking=yes`.
5. Сервер принимает public key только для назначенного порта.

### Windows RDP listener trust

Опциональный trusted RDP certificate lifecycle работает отдельно:

```text
Let’s Encrypt public-IP certificate on Bakunity server
        |
        | Hermes-owned renewal timer
        v
non-secret desired certificate state
        |
        | authenticated device check
        v
Windows LocalSystem rotation worker
        |
        | PFX only on change/drift
        v
LocalMachine\My + NETWORK SERVICE key access
        |
        v
RDP-Tcp CUSTOM certificate binding
```

Это сертификат, который видит стандартный Microsoft Remote Desktop при подключении к `SERVER:RDP_PORT`. Именно он устраняет предупреждение о Windows self-signed listener certificate, если имя/IP в сертификате совпадает с адресом подключения и certificate chain доверена клиентом.

Server-side private key не публикуется как static repository/config material. Certificate package выдаётся только authenticated зарегистрированному устройству через bounded helper path.

## Жизненный цикл устройства

1. Telegram создаёт одноразовый pairing-код.
2. Windows локально генерирует keypair.
3. API проверяет код и public key.
4. Registry выдаёт постоянный RDP-порт и device token.
5. Agent запускает reverse SSH.
6. Если trusted RDP certificate lifecycle включён, installer автоматически создаёт rotation companion и применяет текущий trusted listener certificate.
7. Устройство появляется ONLINE после heartbeat.

Normal Update и Repair используют тот же immutable source ref для основного Agent и certificate lifecycle setup. Отдельная ручная certificate setup-команда после штатного install/update/Repair не требуется.

## Удаление устройства

Server-side DELETE:

- отзывает API-token;
- отзывает SSH public key;
- закрывает listener;
- освобождает порт;
- не удаляет локальные файлы Windows автоматически.

Локальный uninstall:

- удаляет основной Agent task/runtime;
- удаляет certificate rotation task/runtime;
- архивирует активный Bakunity client directory.

После локального uninstall устройство нужно удалить в Telegram для server-side revoke/port release.

## Масштабирование

Стандартный пул `53389–53420` даёт 32 одновременных endpoint. Диапазон можно расширить, но нужно учитывать firewall, мониторинг, лимиты сервера и модель доступа к открытым RDP-портам.
