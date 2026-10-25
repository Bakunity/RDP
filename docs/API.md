# Bakunity RDP API v1

API работает по HTTPS с certificate pinning.

## GET /healthz

```json
{
  "ok": true,
  "service": "hermes-rdp",
  "version": "1.1.0",
  "fingerprint": "...",
  "tunnel": "openssh",
  "ssh_port": 7000
}
```

## POST /v1/pair

```json
{
  "code": "PAIRCODE",
  "display_name": "Windows-PC-01",
  "machine_name": "DESKTOP-EXAMPLE",
  "fingerprint": "machine-uuid",
  "ssh_public_key": "ssh-ed25519 AAAA..."
}
```

Ответ содержит устройство, API-настройки и OpenSSH-параметры:

```json
{
  "ok": true,
  "device": {
    "id": "...",
    "name": "Windows-PC-01",
    "rdp_port": 53389,
    "token": "..."
  },
  "api": {
    "base_url": "https://SERVER:7443",
    "fingerprint": "..."
  },
  "ssh": {
    "host": "SERVER",
    "port": 7000,
    "user": "hermes-tunnel",
    "host_key": "ssh-ed25519 AAAA...",
    "remote_bind": "0.0.0.0"
  }
}
```

Pairing атомарный: код помечается использованным только после успешного создания устройства.

## POST /v1/devices/{id}/telemetry

Bearer token устройства. Возвращает pending command `on`, `off` или `restart`.

## POST /v1/devices/{id}/command-result

Bearer token устройства. Подтверждает выполнение команды.

## POST /v1/devices/{id}/revoke-self

Bearer token устройства. Используется установщиком для отката неудачной регистрации: удаляет устройство, отзывает SSH key и освобождает порт.
