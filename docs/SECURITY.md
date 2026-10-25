# Модель безопасности Bakunity RDP

## Защищаемые активы

- Telegram bot token;
- API certificate private key;
- trusted RDP certificate private key / PFX package;
- Windows Ed25519 private keys;
- device API-tokens;
- pairing-коды;
- Windows credentials;
- SQLite registry.

## Серверные границы

Bakunity использует отдельный `sshd`, не изменяя административный SSH на порту `22`.

Tunnel-user не получает:

- shell;
- PTY;
- SFTP;
- local forwarding;
- agent forwarding;
- X11 forwarding;
- произвольный remote port.

`AuthorizedKeysCommand` выдаёт ключ с ограничениями, а `permitlisten` привязывает его к назначенному RDP-порту.

## Клиентская trust chain

1. HTTPS API проверяется по SHA-256 fingerprint.
2. SSH host key приходит через уже закреплённый API.
3. `StrictHostKeyChecking` запрещает незаметную замену сервера.
4. Private Ed25519 key остаётся на Windows.
5. Secret client files получают ACL только для `SYSTEM` и Administrators.

## HTTPS TLS и RDP TLS — разные границы

Сертификат HTTPS API и сертификат Windows RDP listener решают разные задачи.

**API certificate** используется installer/Agent для pinned HTTPS control plane.

**RDP listener certificate** предъявляется Microsoft Remote Desktop при подключении к публичному Bakunity endpoint. При включённом trusted RDP lifecycle Bakunity получает публично доверенный certificate для публичного IPv4 сервера, доставляет его только authenticated зарегистрированному устройству и привязывает к Windows `RDP-Tcp` как CUSTOM certificate.

Добавление домена или изменение HTTPS certificate само по себе не убирает RDP warning: доверенным должен быть именно сертификат Windows RDP listener, соответствующий адресу подключения.

## Trusted RDP certificate lifecycle

Опциональный server-side lifecycle:

- принимает только глобально маршрутизируемый public IPv4;
- использует ACME HTTP-01 через TCP `80`;
- выполняет staging validation до первой production issuance;
- использует Let’s Encrypt short-lived IP certificate;
- обновляется отдельным Bakunity systemd timer/service;
- публикует Windows только non-secret desired state для обычных rotation checks.

Windows lifecycle:

- отдельный Scheduled Task `Bakunity RDP Certificate Rotation` работает от LocalSystem;
- полный PFX package запрашивается только при новом thumbprint или local listener drift;
- импорт выполняется в `LocalMachine\My` без штатного exportable-флага;
- private key получает необходимый Read для `NETWORK SERVICE`, под которым работает TermService;
- listener переводится в CUSTOM binding только после успешной проверки;
- setup/sync имеют rollback boundary.

`Non-exportable` снижает риск обычного API-export, но не является защитой от полностью скомпрометированного Windows Administrator/SYSTEM endpoint. Компрометация привилегированного Windows-хоста остаётся отдельной security boundary.

Certificate worker вынесен из основного 3-секундного Agent loop и использует отдельный global mutex с доступом только для LocalSystem и Builtin Administrators.

## Pairing

Код одноразовый и ограничен по времени. Device создаётся после проверки структуры Ed25519 public key.

При ошибке после pairing установщик пытается отозвать созданное устройство, чтобы не оставлять активный key и занятый порт.

## Telegram

Контроллер сверяет chat ID и actor ID. Bot token хранится в root-owned файле и не должен попадать в команды, логи, скриншоты или git.

## RDP boundary

Bakunity защищает регистрацию, ключи, control plane, tunnel и при включённом trusted lifecycle — проверяемость TLS identity Windows RDP listener. Но Bakunity не заменяет Windows authentication/authorization самой RDP-сессии.

Внешний endpoint доступен как TCP-порт сервера. Обязательны:

- сильный уникальный Windows-пароль;
- NLA;
- актуальные обновления Windows;
- минимальное число администраторов;
- ограничение source IP или дополнительный сетевой контроль, когда сценарий это допускает;
- мониторинг неудачных входов.

Не используйте пустые пароли или общие пароли между устройствами.

## Отзыв

DELETE должен:

- отозвать API-token;
- отозвать SSH public key;
- завершить listener;
- освободить порт.

Украденный старый SSH key после отзыва не должен аутентифицироваться.

Локальный uninstall отдельно удаляет Bakunity Agent и certificate rotation runtime. После uninstall всё равно выполните DELETE в Telegram для server-side revoke.

## Backup и restore

Backup содержит чувствительные данные. Храните его с mode `0700`, не загружайте в публичные облака без шифрования и не прикладывайте к issue.

Если включён trusted RDP lifecycle, server backup/restore также требует аккуратно обращаться с `/etc/letsencrypt` и Bakunity certificate configuration/state. Не публикуйте ACME private keys или PFX packages.

После restore проверьте permissions, `doctor`, SSH host key, certificate renewal timer/state и существующие устройства.

## Что не публиковать

Не публикуйте:

- bot token;
- pairing-код;
- TLS fingerprint вместе с готовой командой установки;
- private SSH key;
- certificate private key или PFX/password;
- `device.json`;
- полный agent log;
- реальные IP и Telegram IDs из production без необходимости.

## Сообщение об уязвимости

Используйте процедуру из [корневого SECURITY.md](../SECURITY.md). Не публикуйте рабочий exploit или секреты в открытом issue.
