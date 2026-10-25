# Миграция с FRP на OpenSSH

Переход с `v1.0.x` требует повторного pairing каждого Windows-ПК: старые FRP credentials не преобразуются в SSH keys.

## Перед началом

1. Проверьте административный SSH на `22/tcp`.
2. Создайте backup:
   - `/etc/hermes-rdp`;
   - `/etc/frp`;
   - `/var/lib/hermes-rdp`;
   - systemd units.
3. Зафиксируйте текущую версию.
4. Убедитесь, что знаете рабочий путь rollback.

## Сервер

Запустите актуальный установщик с явным `--migrate`:

```bash
sudo env HERMES_RDP_REF=REF bash /tmp/install-bakunity-rdp.sh \
  --host SERVER_IP_OR_DOMAIN \
  --telegram-token "$TG_TOKEN" \
  --telegram-chat-id TELEGRAM_USER_ID \
  --migrate
```

После миграции проверьте:

```bash
sudo hermes-rdpctl doctor
sudo systemctl is-active hermes-rdp-sshd.service hermes-rdp.service
command -v frps || true
systemctl is-enabled frps.service 2>/dev/null || true
```

Ожидается:

- два Bakunity OpenSSH service active;
- `frps` binary отсутствует;
- `frps.service` отсутствует или disabled;
- база содержит SSH-поля;
- старые устройства без SSH public key отозваны.

## Windows

Актуальный установщик:

- останавливает старые FRP/WinMon задачи;
- переносит старый каталог в `HermesRDP-legacy-*`;
- создаёт новый Ed25519 keypair;
- регистрирует устройство заново;
- создаёт новую Scheduled Task;
- не использует `frpc.exe`.

Каждый ПК нужно добавить через новый pairing-код Telegram.

## Найденная проблема старых ACL

Старый private key мог быть доступен только `SYSTEM`, из-за чего рекурсивный backup завершался `Access denied`.

Правильное поведение нового установщика:

1. остановить старые задачи и процессы;
2. перенести legacy-каталог целиком;
3. при необходимости применить `takeown`/`icacls` только к каталогу Bakunity;
4. только после локальной подготовки начинать pairing.

## После миграции

- пройдите внешний RDP-тест;
- перезагрузите Windows и проверьте reconnect;
- проверьте `OFF`, `ON`, `RESTART` и `DELETE`;
- добавьте второй ПК;
- удаляйте legacy backup только после полного PASS.

Полный список: [TESTING_A_TO_Z.md](TESTING_A_TO_Z.md).
