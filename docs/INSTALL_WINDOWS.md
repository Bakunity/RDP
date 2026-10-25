# Установка Windows-клиента

## Требования

- Windows 10/11 Pro, Enterprise или Education x64 либо поддерживаемая Windows Server;
- PowerShell 5.1+;
- права локального администратора;
- Microsoft OpenSSH Client;
- доступ к Bakunity server на API и tunnel ports.

Windows Home не поддерживает входящие RDP-сессии штатными средствами.

Windows 10 x64 поддерживается и из 32-битного Windows PowerShell: installer использует native system path/Sysnative для Microsoft OpenSSH и native PowerShell, когда это необходимо.

## Fresh pairing нового ПК

1. В Telegram отправьте `/start`.
2. Нажмите **➕ ДОБАВИТЬ ПК**.
3. Откройте PowerShell от имени администратора.
4. Скопируйте команду из Telegram целиком.
5. Введите название компьютера.

Pairing-код одноразовый и ограничен по времени. Если он истёк или уже использован, нажмите **🔁 НОВЫЙ КОД** и используйте обновлённую команду.

Fresh installer создаёт новую device registration и локальную Ed25519 identity только для нового клиента. Private key остаётся на Windows; сервер получает только public key.

Installer также автоматически подключает certificate lifecycle, если trusted RDP certificate включён на сервере. Отдельную ручную команду настройки сертификата после обычного fresh install выполнять не нужно.

## Что создаётся на Windows

Основной runtime:

- `C:\ProgramData\HermesRDP\device.json`;
- отдельный Ed25519 keypair;
- отдельный `known_hosts`;
- `HermesRdpAgent.ps1`;
- Scheduled Task `Bakunity RDP Agent`, работающий от `SYSTEM`.

При включённом trusted RDP certificate lifecycle дополнительно управляются:

- `HermesRdpCertRotation.ps1`;
- `sync-rdp-certificate.ps1`;
- Scheduled Task `Bakunity RDP Certificate Rotation` от LocalSystem;
- trusted certificate в `LocalMachine\My`;
- CUSTOM certificate binding Windows RDP listener.

Certificate worker работает отдельно от основного 3-секундного Agent loop и по умолчанию проверяет non-secret desired certificate state с низкой частотой. Полный certificate package запрашивается только при изменении thumbprint или локальном drift.

## Успешный результат fresh install

```text
=== ГОТОВО ===
Компьютер: office-pc
RDP: SERVER:53389
Туннель: OpenSSH
Задача: Bakunity RDP Agent
Сертификат RDP: автоматическое управление
```

Если server-side trusted certificate lifecycle включён, после установки ожидаются также работающая rotation task и CUSTOM RDP listener certificate.

## Уже установлен Bakunity: используйте Repair

Если ПК уже зарегистрирован в Telegram и локальная identity сохранена, не запускайте новый fresh pairing. В карточке существующего устройства нажмите **🛠 ВОССТАНОВИТЬ КЛИЕНТ**.

Repair сохраняет:

- Device ID и API-token;
- Ed25519 keypair;
- `known_hosts`;
- назначенный RDP-порт.

Repair может восстановить Bakunity Agent, основной Scheduled Task и certificate-rotation companion существующего устройства. Он привязан к выбранному Device ID и не создаёт вторую device registration.

Успех основного Repair подтверждается строкой:

```text
REPAIR=PASS
```

Lifecycle wrapper дополнительно подтверждает управление сертификатом и завершает полный Repair только после успешной certificate sub-operation.

Если потеряны `device.json`, private key или `known_hosts`, обычный Repair намеренно останавливается. Автоматический re-pair/rekey в этот flow не входит.

## Обновление существующего клиента

`scripts/update-client.ps1` предназначен для здоровой существующей установки. Он:

- проверяет baseline;
- разрешает requested ref в immutable SHA;
- заранее скачивает и парсит основной Agent и certificate lifecycle setup из одного SHA;
- сохраняет previous agent/task snapshot;
- не переписывает identity/config/trust material;
- применяет certificate lifecycle до финального `UPDATE=PASS`;
- при failure после mutation выполняет automatic rollback.

Если baseline уже повреждён, используйте Repair, а не fresh pairing.

## Проверка

Основной runtime:

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Agent'
Get-Process ssh -ErrorAction SilentlyContinue
Get-Content 'C:\ProgramData\HermesRDP\agent.log' -Tail 100
```

Certificate lifecycle:

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Certificate Rotation'
Get-CimInstance -Namespace 'root/cimv2/TerminalServices' -ClassName Win32_TSGeneralSetting -Filter "TerminalName='RDP-tcp'" | Select-Object SSLCertificateSHA1Hash,SSLCertificateSHA1HashType
```

Для trusted CUSTOM binding `SSLCertificateSHA1HashType` должен быть `3`.

После локальной проверки выполните свежий внешний Microsoft Remote Desktop test через назначенный endpoint и убедитесь, что при включённом trusted certificate lifecycle клиент не показывает прежнее self-signed warning.

## Uninstall

`scripts/uninstall-client.ps1` удаляет active Bakunity runtime локально:

- останавливает и unregister-ит `Bakunity RDP Agent`;
- останавливает и unregister-ит `Bakunity RDP Certificate Rotation`;
- завершает Bakunity Agent/rotation/SSH процессы;
- переносит активный `C:\ProgramData\HermesRDP` в timestamped removal archive.

После локального uninstall удалите устройство в Telegram, чтобы сервер отозвал API-token/SSH public key и освободил назначенный RDP-порт.

## Безопасность

Не публикуйте pairing-коды, API-token, private key или PFX material. Bakunity не требует ослабления Microsoft Defender для штатной установки, update, Repair или certificate rotation.
