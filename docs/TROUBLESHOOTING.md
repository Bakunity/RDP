# Диагностика Bakunity RDP

## Сервер не проходит `doctor`

```bash
sudo hermes-rdpctl doctor
sudo systemctl status hermes-rdp-sshd.service hermes-rdp.service --no-pager
sudo journalctl -u hermes-rdp.service -n 100 --no-pager
```

Сначала исправляйте первую конкретную ошибку, а не перезапускайте всё подряд.

## Порт `7000` не слушается

```bash
sudo /usr/sbin/sshd -t -f /etc/hermes-rdp/sshd_config
sudo journalctl -u hermes-rdp-sshd.service -n 100 --no-pager
sudo ss -ltnp 'sport = :7000'
```

Типичные причины:

- некорректный `sshd_config`;
- занят порт;
- отсутствует SSH host key;
- неверные permissions конфигурации или ключа.

## API `7443` недоступен

```bash
sudo systemctl status hermes-rdp.service --no-pager
sudo journalctl -u hermes-rdp.service -n 100 --no-pager
sudo ss -ltnp 'sport = :7443'
```

Проверьте firewall и совпадение адреса в сертификате с `public_host`.

## Windows installer: `Access denied` в старом `winmon` или ключе

Используйте актуальный установщик. Он переносит legacy-каталог целиком и при необходимости исправляет ACL только внутри:

```text
C:\ProgramData\HermesRDP
```

Не отключайте Microsoft Defender целиком и не удаляйте private keys вручную до сохранения backup.

## `SSH-туннель не запустился`

```powershell
Get-ScheduledTaskInfo -TaskName 'Bakunity RDP Agent'
Get-Content 'C:\ProgramData\HermesRDP\agent.log' -Tail 100
Get-Process ssh -ErrorAction SilentlyContinue
Test-NetConnection SERVER_IP_OR_DOMAIN -Port 7000
```

Проверьте:

- наличие `ssh.exe` и `ssh-keygen.exe`;
- доступ к `7000/tcp`;
- корректный `known_hosts`;
- наличие private key;
- отсутствие другого процесса, занявшего тот же remote port.

## ПК OFFLINE в Telegram

Проверьте:

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Agent'
Get-Content 'C:\ProgramData\HermesRDP\agent.log' -Tail 100
Test-NetConnection SERVER_IP_OR_DOMAIN -Port 7443
```

OFFLINE обычно означает отсутствие свежего heartbeat, а не обязательно поломку RDP.

## RDP-порт закрыт

До поднятия reverse-туннеля это нормально.

После запуска Windows:

```bash
sudo ss -ltnp 'sport = :53389'
```

Если вывода нет, ищите проблему в SSH agent и `hermes-rdp-sshd`.

## RDP-порт открыт, но вход не проходит

Проверьте на Windows:

```powershell
Get-Service TermService
Get-NetFirewallRule -Name 'RemoteDesktop-*' -ErrorAction SilentlyContinue
```

Также проверьте:

- поддерживаемую редакцию Windows;
- NLA;
- правильное имя пользователя и пароль;
- отсутствие блокировки учётной записи;
- актуальные Windows updates.

Bakunity не обходит Windows authentication.

## Pairing-код не принимается

Создайте новый код в Telegram. Код одноразовый и имеет ограниченный срок жизни.

Не публикуйте код и fingerprint в чате поддержки или issue.

## Устройство удалено, но локальный агент остался

Сервер уже не примет отозванный key. Для локальной очистки запустите `scripts/uninstall-client.ps1` от администратора.

## Что присылать для диагностики

Можно прислать:

- названия этапов и текст ошибки;
- `systemctl is-active`;
- последние строки журнала после удаления секретов;
- факт, слушается порт или нет.

Нельзя присылать:

- bot token;
- pairing-код;
- private key;
- `device.json`;
- полный fingerprint вместе с готовой командой установки;
- реальные Telegram IDs без необходимости.
