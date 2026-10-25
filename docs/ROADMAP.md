# Roadmap Bakunity RDP

Roadmap описывает направления после v1.0.0. Это не список уже реализованных возможностей.

## Надёжность

- versioned SQLite migrations;
- transactional update и automatic rollback;
- integration tests API + simulated client;
- end-to-end FRPS/FRPC smoke test;
- проверка server config до restart;
- backup restore test в CI;
- улучшенная ротация логов Windows agent.

## Безопасность

- per-device FRP authentication вместо общего token;
- автоматическая ротация device credentials;
- optional mTLS для API;
- rate limiting pairing/auth failures;
- audit log Telegram/CLI actions;
- optional IP allowlist для RDP endpoints;
- signed release manifests;
- encrypted backups.

## Управление устройствами

- rename из Telegram;
- tags и groups;
- maintenance mode;
- scheduled ON/OFF;
- уведомления ONLINE/OFFLINE;
- command/result history;
- configurable telemetry interval.

## Эксплуатация

- optional web admin panel;
- Prometheus metrics;
- structured JSON logs;
- alerts по CPU/RAM/disk;
- stale device policy;
- deb package для server.

## Networking

- friendly DNS names для устройств;
- optional private WireGuard mode;
- IPv6 support;
- multiple Bakunity servers и failover;
- regional relays.

## Границы core

- проект не хранит Windows/RDP passwords;
- не обходит ограничения редакций Windows;
- не создаёт отдельную ветку кода для «главного ПК»;
- Telegram не используется как транспорт RDP traffic.

## Правило принятия feature

Новая функция должна:

1. сохранять равноправие Windows-клиентов;
2. иметь понятную security model;
3. иметь upgrade/migration path;
4. иметь тесты;
5. быть документирована;
6. не ломать существующие endpoints без major release.
