# Эксплуатация Bakunity RDP

## Быстрая проверка состояния

```bash
sudo hermes-rdpctl doctor
sudo systemctl status hermes-rdp-sshd.service hermes-rdp.service --no-pager
sudo ss -ltnp | grep -E ':(7000|7443|5338[9]|5339[0-9])\b'
```

Если trusted RDP certificate lifecycle включён:

```bash
sudo systemctl status hermes-rdp-cert-renew.timer --no-pager
sudo cat /etc/hermes-rdp/trusted-rdp-cert-state.json
```

## Логи сервера

```bash
sudo journalctl -u hermes-rdp-sshd.service -n 100 --no-pager
sudo journalctl -u hermes-rdp.service -n 100 --no-pager
sudo journalctl -u hermes-rdp-cert-renew.service -n 100 --no-pager
```

Последняя команда нужна только при включённом trusted certificate lifecycle.

Логи могут содержать адреса и идентификаторы. Перед публикацией удаляйте pairing-коды, tokens, fingerprints и реальные IP/Telegram IDs.

## Перезапуск

```bash
sudo systemctl restart hermes-rdp-sshd.service hermes-rdp.service
```

После перезапуска Windows-агенты должны переподключиться автоматически.

Certificate renewal timer не входит в обычный restart controller/tunnel services и живёт отдельным lifecycle.

## Backup

Сохраняйте:

- `/etc/hermes-rdp`;
- `/var/lib/hermes-rdp/state.sqlite3`;
- systemd units;
- текущий repository ref.

При включённом trusted RDP lifecycle дополнительно учитывайте `/etc/letsencrypt` и Bakunity certificate renewal units/helpers. Эти данные содержат private key material и требуют более строгого хранения.

Базовый backup:

```bash
sudo tar -C / -czf /var/backups/hermes-rdp/manual-$(date -u +%Y%m%dT%H%M%SZ).tar.gz \
  etc/hermes-rdp \
  var/lib/hermes-rdp \
  etc/systemd/system/hermes-rdp.service \
  etc/systemd/system/hermes-rdp-sshd.service
```

Проверьте, что архив создан и не пуст:

```bash
sudo ls -lh /var/backups/hermes-rdp/manual-*.tar.gz | tail
```

Не публикуйте backup и не копируйте certificate private keys/PFX material в issue/chat.

## Обновление сервера

1. Прочитайте release notes.
2. Создайте backup.
3. Используйте фиксированный release tag или проверенный commit.
4. Запустите `scripts/update-server.sh`.
5. Выполните `hermes-rdpctl doctor`.
6. Если trusted certificate lifecycle включён, проверьте renewal timer и non-secret state.
7. Проверьте существующий Windows endpoint из внешней сети.

Не обновляйте production прямо с изменяемого `main`.

## Обновление Windows-клиента

Normal `update-client.ps1` теперь управляет не только основным Agent, но и certificate rotation companion из того же immutable source ref.

Успешный update должен оставить:

- Device ID / API-token / Ed25519 identity / `known_hosts` / RDP port неизменными;
- `Bakunity RDP Agent` здоровым;
- `Bakunity RDP Certificate Rotation` здоровым, если trusted lifecycle включён;
- trusted CUSTOM listener сохранённым;
- TCP 3389 слушающим.

Certificate sub-operation выполняется до финального `UPDATE=PASS`; failure участвует в transactional rollback boundary.

## Repair Windows-клиента

Repair существующего устройства сохраняет identity/port и может восстановить как основной Agent/task, так и certificate rotation worker/task.

Repair не является fresh pairing и не должен автоматически rekey/re-register устройство при потере обязательной локальной identity.

## Trusted certificate renewal и rotation

Server-side timer периодически запускает bounded renewal path. При not-due renewal certificate не меняется.

После реального изменения certificate thumbprint:

1. Bakunity обновляет non-secret server certificate state.
2. Windows rotation worker видит новый desired thumbprint.
3. Только тогда authenticated клиент получает новый certificate package.
4. Windows worker импортирует certificate и обновляет CUSTOM RDP listener binding.

Не форсируйте лишнюю production issuance только ради проверки. Для обычной эксплуатации достаточно наблюдать естественный renewal.

## Windows certificate diagnostics

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Certificate Rotation'
Get-CimInstance -Namespace 'root/cimv2/TerminalServices' -ClassName Win32_TSGeneralSetting -Filter "TerminalName='RDP-tcp'" | Select-Object SSLCertificateSHA1Hash,SSLCertificateSHA1HashType
```

CUSTOM binding имеет `SSLCertificateSHA1HashType = 3`.

## Отзыв устройства

Удаление в Telegram:

- отзывает API-token;
- отзывает SSH public key;
- закрывает listener;
- освобождает порт.

После удаления проверьте:

```bash
sudo ss -H -ltn 'sport = :53389'
```

Вывод должен быть пустым для освобождённого endpoint.

## Локальный uninstall Windows

Normal uninstall:

- unregister-ит `Bakunity RDP Agent`;
- unregister-ит `Bakunity RDP Certificate Rotation`;
- останавливает Bakunity Agent/rotation/SSH processes;
- архивирует активный `C:\ProgramData\HermesRDP`.

После локального uninstall удалите устройство в Telegram, чтобы завершить server-side revoke и port release.

## После перезагрузки сервера

```bash
sudo systemctl is-active hermes-rdp-sshd.service hermes-rdp.service
sudo hermes-rdpctl doctor
```

Оба systemd service должны стартовать автоматически. Windows-агенты должны восстановить свои listeners после reconnect.

Если trusted certificate lifecycle включён, `hermes-rdp-cert-renew.timer` также должен оставаться enabled/active.

## После перезагрузки Windows

Основной Scheduled Task запускается от `SYSTEM` с задержкой. В течение 30–90 секунд ожидаются:

- процесс `ssh.exe`;
- новый heartbeat;
- ONLINE в Telegram;
- открытый назначенный порт на сервере.

Certificate rotation task работает отдельно и не должна создавать второй Bakunity SSH transport.

## Ротация и очистка

- храните ограниченное число проверенных backups;
- не удаляйте последний рабочий backup до полного acceptance PASS;
- legacy-каталоги Windows удаляйте только после проверки новой установки;
- не оставляйте отозванные устройства в registry без причины;
- не удаляйте активную Let’s Encrypt lineage вручную без отдельного recovery plan.
