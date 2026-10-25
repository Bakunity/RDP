# Проверенные сценарии

Этот документ фиксирует фактически выполненные проверки без публикации секретов и реальных production-идентификаторов.

## Подтверждено

### Сервер и OpenSSH transport

- чистая установка Linux-сервера;
- `hermes-rdp-sshd.service` и `hermes-rdp.service` active/enabled;
- отдельный Bakunity `sshd` на `7000/tcp` не зависит от admin SSH `:22`;
- FRP отсутствует из текущего runtime;
- SQLite registry и OpenSSH device fields работают;
- сервер после reboot восстанавливает controller/tunnel services, а Windows agents переподключаются автоматически.

### Windows pairing и совместимость

- fresh pairing создаёт локальный Ed25519 keypair;
- private key остаётся на Windows, сервер получает только public key;
- Scheduled Task `Bakunity RDP Agent` работает от `SYSTEM`;
- Windows 10 x64 из 32-битного PowerShell корректно использует native OpenSSH через Sysnative;
- Windows Server 2019 проходит fresh install и end-to-end RDP;
- повторный `Добавить ПК` на уже установленной машине не выполняет destructive actions;
- pairing-код одноразовый и ограничен по времени;
- кнопка `🔁 НОВЫЙ КОД` выдаёт новый код и обновляет installer command вместе с ним.

### Несколько устройств и RDP

- несколько Windows-ПК одновременно держат независимые reverse SSH-туннели;
- каждому устройству назначается постоянный отдельный внешний RDP-порт;
- два Microsoft RDP-сеанса к разным Hermes-устройствам работают одновременно;
- отключение/сбой одного устройства не ломает другое;
- внешний RDP из отдельной сети проходит полный путь:

```text
remote client → Linux server → reverse SSH → Windows RDP
```

### Telegram control

- `OFF` закрывает публичный listener и прерывает Bakunity RDP access;
- agent heartbeat остаётся отдельным от состояния доступа;
- `ON` восстанавливает listener и возможность подключения;
- `RESTART` заменяет Bakunity SSH transport и возвращает ровно один tunnel;
- dashboard автоматически обновляет command/tunnel state;
- mobile layout кнопок принят в live usage.

### Recovery и lifecycle

- Windows reboot recovery — PASS;
- Linux server reboot recovery — PASS;
- временный Windows-side transport loss восстанавливается автоматически;
- controller restart не требует перезапуска RDP transport;
- dedicated Bakunity sshd restart восстанавливает Windows tunnels;
- повторные sshd reconnect cycles не оставили server-side duplicate/orphan sessions;
- hard delete отзывает API-token/public key, закрывает listener и освобождает порт;
- освобождённый порт безопасно используется следующим fresh pairing;
- stale deleted identity не реконструировалась искусственно ради теста: старый raw-client fixture недоступен.

### Security boundaries

- per-device Ed25519 identities изолированы;
- cross-device SSH access не разрешён;
- Telegram control ограничен owner chat/user ID;
- admin SSH `:22` и Bakunity tunnel SSH `:7000` имеют отдельные service/config/process boundaries;
- Bakunity не добавляет Microsoft Defender exclusions и не требует отключения Defender;
- на acceptance fixtures real-time protection работала вместе с Bakunity RDP.

### Trusted public-IP RDP certificate lifecycle

- публичный IPv4 прошёл ACME HTTP-01 reachability validation;
- isolated Certbot installation и Let’s Encrypt staging validation — PASS;
- production short-lived public-IP certificate issuance — PASS;
- certificate/private-key match и trust-chain validation — PASS;
- Hermes-owned renewal service/timer enabled/active;
- normal not-due renewal smoke не меняет certificate и освобождает TCP 80 после работы;
- authenticated certificate package delivery зарегистрированному Windows device — PASS;
- certificate imported в `LocalMachine\My` без штатного exportable-флага;
- необходимый `NETWORK SERVICE` Read ACL применён;
- Windows `RDP-Tcp` переключён на CUSTOM certificate binding;
- TCP 3389 остался listening;
- свежий Microsoft Remote Desktop connection принял certificate без прежнего self-signed warning.

### Trusted certificate rollback и drift recovery

- исходный Windows default self-signed listener state был зафиксирован до mutation;
- ошибочная попытка восстановить default self-signed thumbprint как CUSTOM была поймана как реальный bug;
- корректный rollback удалением explicit custom binding восстановил исходный default self-signed state;
- trusted certificate после rollback успешно применён повторно;
- controlled local drift обратно в self-signed state был обнаружен automatic rotation worker;
- worker выполнил `CERT_ROTATION=UPDATED` и восстановил trusted CUSTOM binding;
- свежий Microsoft RDP после automatic recovery снова был trusted.

### Automatic certificate rotation worker

- отдельный Windows Scheduled Task `Bakunity RDP Certificate Rotation` работает от LocalSystem SID `S-1-5-18`;
- worker выполняет lightweight authenticated status check до PFX retrieval;
- при unchanged thumbprint полный certificate package не передаётся;
- global mutex ACL ограничен LocalSystem + Builtin Administrators;
- live upgrade bug с SYSTEM-owned mutex был воспроизведён, rollback прошёл, fix принят;
- certificate work не возвращено в performance-sensitive 3-second Agent loop.

### Performance и telemetry

- тяжёлые WMI/NetTCPIP операции убраны из ordinary fast path;
- измеренный fast core выполнялся за десятки миллисекунд, а не занимал большую часть telemetry interval;
- `НАБЛЮДАТЬ 60с` включает более частую heavy telemetry только на bounded lease;
- пользовательская работа через Bakunity RDP после оптимизации подтверждена как плавная без заметных прежних микрофризов.

### Transactional update

- server updater делает consistent SQLite backup, app/config/unit backup и metadata перед mutation;
- успешный server update сохраняет device state и endpoints;
- deliberate server post-mutation failure вызвал automatic rollback с восстановлением app/config/units/database/services/endpoints;
- Windows updater сохраняет identity/config/keys/known-hosts/port и Scheduled Task;
- deliberate Windows post-mutation failure вызвал product rollback и восстановил предыдущий agent/runtime;
- normal Windows Update автоматически управляет certificate rotation companion из того же immutable source SHA;
- live CERT-013 Update сохранил identity/port/main runtime/trusted CUSTOM listener и завершился `CERT-013_UPDATE=PASS`.

### Existing-device Repair

- отдельный Repair не выполняет fresh pairing и не создаёт второе устройство;
- Repair сохраняет `device.json`, API-token, Ed25519 identity, `known_hosts` и назначенный порт;
- на acceptance fixture удалённые agent file + Scheduled Task были восстановлены с `REPAIR=PASS`;
- deliberate failure после candidate mutation вызвал `ROLLBACK=PASS` и восстановил предыдущий agent/task;
- Telegram repair screen выдаёт immutable command, bound to selected Device ID;
- если локальная identity/config/private key/known-hosts потеряны, обычный Repair намеренно останавливается без автоматического rekey;
- CERT-013 targeted Repair с удалёнными только rotation task + worker автоматически восстановил certificate companion без изменения identity, port или trusted RDP binding;
- итоговый lifecycle marker `CERT-013_REPAIR_LIVE=PASS`.

### Fresh install / uninstall с integrated certificate lifecycle

На отдельной disposable Windows 10 Pro x64 fixture с PowerShell 5.1 и включённым Defender подтверждено:

- до установки Bakunity base/tasks/processes отсутствовали;
- fresh installer автоматически создал основной Agent runtime и certificate rotation companion;
- rotation task работает как LocalSystem SID `S-1-5-18`;
- trusted CUSTOM RDP listener применён автоматически;
- ровно один Bakunity Agent и один Bakunity SSH transport;
- Defender остался включён, Bakunity exclusion не добавлялся;
- внешний Microsoft Remote Desktop через назначенный Bakunity endpoint подключился успешно и без self-signed warning;
- normal uninstall удалил обе Bakunity Scheduled Tasks и остановил Agent/rotation/SSH runtime;
- active `C:\ProgramData\HermesRDP` был архивирован/удалён;
- Defender real-time protection остался включён;
- финальный marker `CERT-013_UNINSTALL=PASS`.

## Отдельно не закрыто

### Natural renewal-driven rotation — deferred observation

Полный synthetic drift path уже принят. Отдельно остаётся только наблюдение следующего **естественного** production renewal: новый server thumbprint → state refresh → automatic Windows rotation → fresh trusted RDP.

Не форсировать дополнительную production issuance исключительно ради этой проверки.

### RL-006 — PARTIAL PASS

Пять repeated dedicated-sshd reconnect cycles были чистыми server-side. На исходной exact Windows-машине после этой серии не был снят финальный lightweight count `HermesSshCount == 1`. Повторять пятицикловый stress не требуется; если exact fixture снова доступна, достаточно одного process-count check.

### SEC-004 — fixture unavailable

Проверка «старый удалённый raw-client credential не может reclaim device/port» не была повторно live-exercised, потому что нужный старый fixture/credential уже отсутствует. Не следует реконструировать отозванные credentials только ради искусственного теста.

## Правило обновления

Новый PASS добавляется сюда только после runtime output, CI или явного user confirmation. Pairing-коды, API tokens, private keys, реальные Telegram IDs, production IP и готовый secret material в документ не записываются.
