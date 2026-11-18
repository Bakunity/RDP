param(
    [string]$RepositoryRef = 'main'
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$ParentDir = Split-Path -Parent $BaseDir
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$FailedDir = "$BaseDir.failed-replace.$Stamp"
$RepairCandidate = Join-Path ([IO.Path]::GetTempPath()) (
    "HermesRdpReplaceRecovery-$([Guid]::NewGuid().ToString('N')).ps1"
)

Write-Host '=== HERMES RDP REPLACE RECOVERY ===' -ForegroundColor Cyan

$Backups = @(
    Get-ChildItem -LiteralPath $ParentDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'HermesRDP.replace.*' } |
        Sort-Object LastWriteTime -Descending
)
if ($Backups.Count -eq 0) {
    throw 'Не найдена резервная копия HermesRDP.replace.* для восстановления.'
}

$Backup = $Backups[0]
$BackupConfig = Join-Path $Backup.FullName 'device.json'
if (-not (Test-Path -LiteralPath $BackupConfig)) {
    throw "В резервной копии отсутствует device.json: $($Backup.FullName)"
}

$Config = Get-Content -LiteralPath $BackupConfig -Raw | ConvertFrom-Json
$DeviceId = [string]$Config.device_id
$OldServer = [string]$Config.server
if ([string]::IsNullOrWhiteSpace($DeviceId)) {
    throw 'В backup device.json отсутствует device_id.'
}

Write-Host "Backup: $($Backup.FullName)"
Write-Host "Старый сервер: $OldServer"
Write-Host "DeviceId: $DeviceId"

# A disconnected RDP installer can remain blocked on Read-Host forever.
# Stop only the temporary REPLACE/core PowerShell processes, never this
# recovery process.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        [int]$_.ProcessId -ne [int]$PID -and
        $_.CommandLine -and (
            $_.CommandLine.Contains('HermesRdpInstallReplace-') -or
            $_.CommandLine.Contains('HermesRdpInstallCore-')
        )
    } |
    ForEach-Object {
        Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
    }

Stop-ScheduledTask -TaskName 'Hermes RDP Agent' -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName 'Hermes RDP Certificate Rotation' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'Hermes RDP Agent' -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'Hermes RDP Certificate Rotation' -Confirm:$false -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($BaseDir)
    } |
    ForEach-Object {
        Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
    }

if (Test-Path -LiteralPath $BaseDir) {
    Move-Item -LiteralPath $BaseDir -Destination $FailedDir
    Write-Host "Незавершённая новая установка сохранена: $FailedDir"
}

Move-Item -LiteralPath $Backup.FullName -Destination $BaseDir
Write-Host 'Старая identity возвращена на место.'

$ClientRefPath = Join-Path $BaseDir 'client-ref.txt'
$RecoveryRef = $RepositoryRef
if (Test-Path -LiteralPath $ClientRefPath) {
    $CandidateRef = (Get-Content -LiteralPath $ClientRefPath -Raw).Trim()
    if ($CandidateRef -match '^[0-9a-fA-F]{40}$') {
        $RecoveryRef = $CandidateRef.ToLowerInvariant()
    }
}

$RepairUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$RecoveryRef/scripts/repair-client.ps1"
)
try {
    Invoke-WebRequest -UseBasicParsing -Uri $RepairUrl -OutFile $RepairCandidate

    $Tokens = $null
    $Errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $RepairCandidate,
        [ref]$Tokens,
        [ref]$Errors
    )
    if ($Errors.Count -gt 0) {
        throw "Repair script parse error: $($Errors[0].Message)"
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RepairCandidate `
        -RepositoryRef $RecoveryRef `
        -ExpectedDeviceId $DeviceId
    if ($LASTEXITCODE -ne 0) {
        throw "Repair завершился с кодом $LASTEXITCODE"
    }

    Write-Host
    Write-Host 'REPLACE_RECOVERY=PASS' -ForegroundColor Green
    Write-Host "Старое подключение к $OldServer восстановлено."
}
finally {
    Remove-Item -LiteralPath $RepairCandidate -Force -ErrorAction SilentlyContinue
}
