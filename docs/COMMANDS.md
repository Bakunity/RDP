# Команды

## Сервер

```bash
sudo hermes-rdpctl doctor
sudo hermes-rdpctl devices list
sudo hermes-rdpctl pair create --name 'Windows-PC-01' --port 53389
sudo hermes-rdpctl devices rename DEVICE_ID 'Новое имя'
sudo hermes-rdpctl devices delete DEVICE_ID
sudo hermes-rdpctl dashboard reset
```

## Windows

```powershell
Get-ScheduledTask -TaskName 'Bakunity RDP Agent'
Start-ScheduledTask -TaskName 'Bakunity RDP Agent'
Stop-ScheduledTask -TaskName 'Bakunity RDP Agent'
Get-Content 'C:\ProgramData\HermesRDP\agent.log' -Tail 50
```
