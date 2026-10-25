# Установка сервера

## Поддерживаемая среда

Debian/Ubuntu, root или sudo, systemd, OpenSSH Server, UFW и Python 3.11+.

## Порты

- `22/tcp` — административный SSH сервера, установщик его не меняет;
- `7000/tcp` — отдельный Bakunity OpenSSH daemon;
- `7443/tcp` — HTTPS API;
- `53389–53420/tcp` — RDP endpoints;
- `80/tcp` — нужен только при включённом trusted RDP certificate lifecycle для ACME HTTP-01.

## Чистая установка

До публикации следующего release tag используйте проверенный immutable source ref, а не изменяемый `main`.

```bash
curl -fsSL https://raw.githubusercontent.com/bakunity/RDP/REF/scripts/install-server.sh -o /tmp/install-bakunity-rdp.sh
read -rsp 'Telegram bot token: ' TG_TOKEN; echo
sudo env HERMES_RDP_REF=REF bash /tmp/install-bakunity-rdp.sh \
  --host SERVER_IP_OR_DOMAIN \
  --telegram-token "$TG_TOKEN" \
  --telegram-chat-id TELEGRAM_USER_ID \
  --api-port 7443 \
  --ssh-port 7000 \
  --port-start 53389 \
  --port-end 53420
unset TG_TOKEN
rm -f /tmp/install-bakunity-rdp.sh
```

## Trusted RDP certificate

Bakunity умеет отдельно от HTTPS API управлять публично доверенным сертификатом **Windows RDP listener**. Это нужно, чтобы стандартный Microsoft Remote Desktop не показывал предупреждение о self-signed сертификате при подключении к публичному endpoint.

Для этого server install запускается с дополнительным флагом:

```bash
sudo env HERMES_RDP_REF=REF bash /tmp/install-bakunity-rdp.sh \
  --host PUBLIC_IPV4 \
  --telegram-token "$TG_TOKEN" \
  --telegram-chat-id TELEGRAM_USER_ID \
  --trusted-rdp-cert
```

Требования этого режима:

- `--host` должен быть глобально маршрутизируемым публичным IPv4;
- TCP `80` должен быть свободен локально и доступен извне для ACME HTTP-01;
- сервер должен иметь доступ к Let’s Encrypt;
- не запускайте второй HTTP service на `:80` во время standalone ACME issuance/renewal.

При включении lifecycle Bakunity:

- устанавливает изолированный Certbot в `/opt/certbot`;
- сначала выполняет staging validation;
- получает production short-lived Let’s Encrypt IP certificate;
- создаёт `hermes-rdp-cert-renew.service` и `hermes-rdp-cert-renew.timer`;
- хранит non-secret certificate state для Windows rotation checks;
- предоставляет authenticated device path для передачи certificate package зарегистрированному Windows-клиенту.

HTTPS API certificate и Windows RDP listener certificate — **разные trust boundaries**. Trusted RDP lifecycle не заменяет API fingerprint pinning.

## Что создаётся

Базовая установка:

- `/opt/hermes-rdp/app`;
- `/etc/hermes-rdp/config.json`;
- `/etc/hermes-rdp/tls/`;
- отдельный SSH host key;
- `/var/lib/hermes-rdp/state.sqlite3`;
- `hermes-rdp.service`;
- `hermes-rdp-sshd.service`;
- системные пользователи `hermes-rdp` и `hermes-tunnel`.

При `--trusted-rdp-cert` дополнительно создаются Bakunity certificate helpers/state и systemd renewal service/timer.

## Проверка

```bash
sudo hermes-rdpctl doctor
sudo systemctl status hermes-rdp-sshd.service hermes-rdp.service --no-pager
sudo /usr/sbin/sshd -t -f /etc/hermes-rdp/sshd_config
sudo ss -ltnp | grep -E ':(7000|7443)\b'
```

Ожидается:

```text
config: OK
api: OK (..., openssh)
ssh-tunnel: LISTEN 7000
api: LISTEN 7443
ssh-config: OK
```

Если включён trusted RDP certificate lifecycle:

```bash
sudo systemctl is-enabled hermes-rdp-cert-renew.timer
sudo systemctl is-active hermes-rdp-cert-renew.timer
sudo cat /etc/hermes-rdp/trusted-rdp-cert-state.json
```

Timer должен быть enabled/active, а state-файл — существовать и содержать только non-secret certificate metadata.

До подключения первого ПК RDP-порты должны быть закрыты. Порт появляется только после успешного reverse-туннеля.

## Backup

Каждый запуск создаёт каталог в `/var/backups/hermes-rdp/`. Не удаляйте backup до прохождения внешнего RDP-теста.

## Повторная установка

Переход с `v1.0.x`/FRP требует явного `--migrate`. Чистой OpenSSH-установке этот флаг не нужен.

## После установки

1. Отправьте `/start` Telegram-боту.
2. Убедитесь, что панель показывает OpenSSH port `7000`.
3. Добавьте первый Windows-ПК.
4. Если включён trusted certificate lifecycle, дождитесь автоматического применения сертификата на Windows.
5. Проверьте endpoint из другой сети стандартным Microsoft Remote Desktop.
