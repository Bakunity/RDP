# Тестирование Bakunity RDP от А до Я

Этот checklist предназначен для тестового сервера перед постоянной эксплуатацией и обязательно включает проверку **внешнего RDP** через Bakunity endpoint.

Не повторяйте destructive или issuance-heavy проверки на production без конкретной regression-причины. Фактически принятые сценарии перечислены в [VALIDATED_SCENARIOS.md](VALIDATED_SCENARIOS.md).

## A. Сервер

- [ ] `hermes-rdpctl doctor` без ошибок.
- [ ] `hermes-rdp-sshd.service` active/enabled.
- [ ] `hermes-rdp.service` active/enabled.
- [ ] `7000/tcp` и `7443/tcp` слушаются.
- [ ] RDP-пул закрыт до подключения устройств.
- [ ] `/usr/sbin/sshd -t -f /etc/hermes-rdp/sshd_config` проходит.
- [ ] FRP service и binary отсутствуют в OpenSSH-установке.

Если включён `--trusted-rdp-cert`:

- [ ] `--host` является глобально маршрутизируемым public IPv4.
- [ ] TCP `80` доступен для ACME HTTP-01 и не занят постоянным локальным listener.
- [ ] `hermes-rdp-cert-renew.timer` enabled/active.
- [ ] `/etc/hermes-rdp/trusted-rdp-cert-state.json` существует и содержит только non-secret certificate state.

## B. Telegram

- [ ] `/start` показывает OpenSSH и список устройств.
- [ ] **➕ ДОБАВИТЬ ПК** создаёт новый одноразовый код.
- [ ] Команда копируется одним блоком.
- [ ] Команда содержит BOM-normalization перед `ScriptBlock.Create`.
- [ ] Посторонний Telegram ID не получает доступ.

## C. Windows fresh install

- [ ] PowerShell запущен администратором.
- [ ] Редакция Windows поддерживает RDP host.
- [ ] OpenSSH Client найден или установлен.
- [ ] Windows 10 x64 при запуске из x86 PowerShell использует native Sysnative path.
- [ ] Legacy Hermes-каталог не блокирует установку.
- [ ] `=== ГОТОВО ===` отображается.
- [ ] Созданы `device.json`, `known_hosts` и Ed25519 keypair.
- [ ] ACL secrets доступны только `SYSTEM` и Administrators.
- [ ] Scheduled Task `Bakunity RDP Agent` активна.
- [ ] Microsoft Defender real-time protection остаётся включённой; Bakunity exclusion не требуется.

При включённом trusted RDP certificate lifecycle:

- [ ] Созданы `HermesRdpCertRotation.ps1` и `sync-rdp-certificate.ps1`.
- [ ] Scheduled Task `Bakunity RDP Certificate Rotation` работает как LocalSystem SID `S-1-5-18`.
- [ ] Windows RDP listener имеет CUSTOM certificate binding (`SSLCertificateSHA1HashType = 3`).
- [ ] TCP `3389` остаётся listening.

## D. Туннель

- [ ] `ssh.exe` запущен.
- [ ] Для устройства работает ровно один Bakunity SSH transport.
- [ ] Назначенный порт слушается на сервере.
- [ ] Другой порт из пула не занят этим ключом.
- [ ] Telegram показывает ONLINE и LIVE-метрики.
- [ ] В `agent.log` нет постоянного reconnect-loop.

## E. RDP

- [ ] Подключение работает из другой сети.
- [ ] Проверен вход с телефона через мобильные данные или иной внешний канал.
- [ ] Используется сильный Windows-пароль.
- [ ] NLA включена.
- [ ] Windows обновлена.

При trusted RDP certificate lifecycle:

- [ ] Fresh Microsoft Remote Desktop connection не показывает прежнее self-signed certificate warning.
- [ ] Certificate, который видит RDP-клиент, соответствует адресу подключения.

## F. Управление

- [ ] `OFF` закрывает listener.
- [ ] `ON` восстанавливает listener.
- [ ] `RESTART` пересоздаёт SSH-процесс.
- [ ] `DELETE` отзывает key и token.
- [ ] После DELETE порт освобождён.

## G. Recovery

- [ ] После перезагрузки Windows туннель возвращается за 30–90 секунд.
- [ ] После перезагрузки сервера оба основных systemd service возвращаются.
- [ ] При trusted lifecycle renewal timer остаётся active/enabled.
- [ ] Краткий обрыв интернета приводит к reconnect.
- [ ] Перезапуск controller не ломает активный sshd.

## H. Несколько устройств

- [ ] Второй ПК получает следующий свободный порт.
- [ ] У второго ПК отдельный Ed25519 public key.
- [ ] Ключ первого ПК не может занять порт второго.
- [ ] Удаление одного устройства не влияет на остальные.
- [ ] Освобождённый порт можно безопасно выдать новому устройству.

## I. Transactional update

- [ ] Перед update создан backup.
- [ ] Используется фиксированный tag или commit.
- [ ] Server update завершает `doctor` без ошибок.
- [ ] Windows update сохраняет Device ID, keys, `known_hosts` и RDP port.
- [ ] Основной Agent/task остаются healthy.
- [ ] При trusted lifecycle rotation task/worker управляются автоматически из того же immutable source ref.
- [ ] Trusted CUSTOM binding и TCP 3389 сохраняются.
- [ ] Failure после mutation приводит к bounded rollback.

## J. Existing-device Repair

- [ ] Repair запускается для выбранного существующего Device ID, а не создаёт fresh pairing.
- [ ] `device.json`, API-token, Ed25519 identity, `known_hosts` и RDP port сохраняются.
- [ ] Missing Agent/task восстанавливаются.
- [ ] При trusted lifecycle missing rotation worker/task восстанавливаются автоматически.
- [ ] Failure после mutation возвращает previous runtime snapshot.
- [ ] Потеря обязательной local identity останавливает Repair вместо скрытого rekey/re-pair.

## K. Uninstall

- [ ] `Bakunity RDP Agent` unregister-ен.
- [ ] `Bakunity RDP Certificate Rotation` unregister-ен, если существовал.
- [ ] Bakunity Agent/rotation/SSH processes отсутствуют.
- [ ] Active `C:\ProgramData\HermesRDP` архивирован/удалён согласно uninstall behavior.
- [ ] Defender остаётся включён.
- [ ] После локального uninstall устройство удалено в Telegram для server-side revoke и освобождения endpoint.

## L. Certificate rotation observation

Synthetic local drift/recovery уже принят как отдельный validated scenario и не должен постоянно повторяться.

Для обычной дальнейшей эксплуатации достаточно при следующем **естественном** renewal убедиться:

- [ ] server certificate thumbprint изменился естественно;
- [ ] non-secret state обновился;
- [ ] Windows worker увидел новый desired thumbprint;
- [ ] automatic rotation завершилась успешно;
- [ ] fresh Microsoft RDP connection остался trusted.

Не форсируйте production issuance только ради этого пункта.

## Критерий PASS

Для нового release-кандидата проверяйте только то, что реально могло регрессировать относительно уже принятого baseline. Минимальный release smoke должен подтвердить:

1. server/controller/tunnel health;
2. fresh или existing-device path, затронутый изменениями;
3. внешний RDP;
4. identity/port preservation для update/Repair;
5. certificate lifecycle, если release меняет его код;
6. отсутствие Defender weakening.

Полный исторический acceptance не требуется прогонять заново без regression evidence.

Текущий фактический прогресс фиксируется в [VALIDATED_SCENARIOS.md](VALIDATED_SCENARIOS.md).
