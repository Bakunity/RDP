# Security Policy

Bakunity RDP публикует RDP endpoints и управляет credentials устройств. Уязвимости следует сообщать приватно.

## Поддерживаемые версии

| Версия | Статус |
|---|---|
| `1.0.x` | поддерживается |
| `< 1.0.0` | не поддерживается |

Исправления безопасности выпускаются PATCH-релизом и описываются в `CHANGELOG.md` и GitHub Release.

## Как сообщить

Используй GitHub Private Vulnerability Reporting, если функция доступна в репозитории. Не создавай публичный issue с:

- действующим Telegram token;
- FRP token;
- device API token;
- pair code;
- private key;
- production database/backup;
- рабочим способом несанкционированного доступа.

В отчёте укажи:

1. затронутую версию/commit;
2. компонент: server, API, Telegram bot, Windows agent, installer или FRP config;
3. условия воспроизведения;
4. ожидаемое и фактическое поведение;
5. потенциальное влияние;
6. минимальный безопасный proof of concept;
7. предложенное исправление, если есть.

## Реакция

Цель проекта:

- подтвердить получение отчёта;
- воспроизвести проблему;
- определить severity;
- подготовить исправление и migration guidance;
- выпустить PATCH-релиз;
- раскрыть детали после доступности исправления.

Точные сроки не гарантируются, так как проект поддерживается небольшой командой.

## Немедленные действия при утечке

- Telegram token: отозвать через BotFather и заменить server secret;
- device token: отозвать device и зарегистрировать заново;
- `frpc.toml`: отозвать device и ротировать общий FRP token;
- API private key: заменить certificate/key и обновить fingerprint клиентов;
- server backup: считать скомпрометированными все содержащиеся credentials.

Полная модель угроз и процедуры ротации: [docs/SECURITY.md](docs/SECURITY.md).
