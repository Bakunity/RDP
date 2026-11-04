# Быстрый старт Bakunity RDP

Этот путь рассчитан на чистый Debian/Ubuntu-сервер и Windows 10/11 Pro, Enterprise или Education.

Stable release: **v1.3.0**.

## 1. Что понадобится

- Linux-сервер с публичным IPv4 или доменом;
- root/sudo и systemd;
- свободные TCP-порты `7000`, `7443` и диапазон RDP;
- Telegram bot token и ваш числовой Telegram ID;
- Windows x64 с правами администратора.

Windows Home не является штатным RDP-host и не поддерживается.

Для trusted certificate именно Windows RDP listener нужен глобально маршрутизируемый public IPv4 и доступный TCP `80` для ACME HTTP-01.

## 2. Установка сервера

Основной zero-config путь для current main:

```bash
curl -fsSL https://raw.githubusercontent.com/bakunity/RDP/main/scripts/install.sh | sudo bash
```

Установщик:

- проверяет Debian/Ubuntu, systemd и APT;
- автоматически определяет глобальный public IPv4;
- безопасно запрашивает Telegram bot token через `/dev/tty` и не печатает его;
- проверяет бота через Telegram API;
- показывает одноразовую команду `/claim <CODE>` для подтверждения владельца;
- устанавливает OpenSSH gateway и при возможности trusted public-IP RDP certificate lifecycle.

Если нужен нестандартный host, ручной Telegram owner ID, фиксированный immutable release tag или другие параметры, используйте **advanced** installer `scripts/install-server.sh`. Для текущего stable **v1.3.0** advanced путь остаётся совместимым с legacy env name `HERMES_RDP_REF`.

Не публикуйте bot token, pairing-код, API fingerprint, PFX material или приватные ключи.

## 3. Проверка сервера

```bash
sudo hermes-rdpctl doctor
sudo systemctl is-active hermes-rdp-sshd.service hermes-rdp.service
sudo ss -ltnp | grep -E ':(7000|7443)\b'
```

Если включён trusted RDP lifecycle:

```bash
sudo systemctl is-active hermes-rdp-cert-renew.timer
sudo cat /etc/hermes-rdp/trusted-rdp-cert-state.json
```

До подключения первого ПК RDP-порты должны быть закрыты.

## 4. Добавление ПК

1. Отправьте `/start` Telegram-боту.
2. Нажмите **➕ ДОБАВИТЬ ПК**.
3. Откройте PowerShell от имени администратора.
4. Вставьте готовую команду из Telegram целиком.
5. Введите понятное название компьютера.
6. Дождитесь `=== ГОТОВО ===`.

Установщик создаёт локальный Ed25519-ключ, проверяет API certificate fingerprint и SSH host key, включает RDP и регистрирует `Hermes RDP Agent`.

Если trusted certificate lifecycle включён на сервере, Fresh Install автоматически создаёт `Hermes RDP Certificate Rotation` и применяет текущий trusted CUSTOM certificate. Отдельная ручная certificate setup-команда не нужна.

## 5. Подключение

```powershell
mstsc.exe /v:SERVER_IP_OR_DOMAIN:53389
```

Первый ПК обычно получает `53389`, следующий — `53390` и так далее.

Проверяйте подключение из другой сети, например через мобильный интернет телефона.

При включённом trusted lifecycle свежий Microsoft Remote Desktop connection должен принимать certificate без прежнего self-signed warning.

## 6. Финальная проверка

- устройство отображается online в Telegram;
- `ssh.exe` работает на Windows;
- назначенный порт слушается на сервере;
- внешний RDP работает из другой сети;
- `Hermes RDP Agent` находится в Running;
- при trusted lifecycle `Hermes RDP Certificate Rotation` работает от LocalSystem, а RDP listener имеет CUSTOM certificate binding;
- Microsoft Defender остаётся включён и Bakunity не требует exclusions;
- после перезагрузки Windows туннель восстанавливается автоматически;
- второй ПК получает отдельный порт и отдельный ключ.

Полная процедура: [TESTING_A_TO_Z.md](TESTING_A_TO_Z.md).
