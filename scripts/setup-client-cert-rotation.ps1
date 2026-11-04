param([string]$RepositoryRef = 'main')

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$TaskName = 'Hermes RDP Certificate Rotation'
$ConfigPath = Join-Path $BaseDir 'device.json'
$WorkerPath = Join-Path $BaseDir 'HermesRdpCertRotation.ps1'
$SyncPath = Join-Path $BaseDir 'sync-rdp-certificate.ps1'
$OriginPath = Join-Path $BaseDir 'rdp-certificate-origin.json'
$LegacyBackupPath = Join-Path $BaseDir 'rdp-certificate-backup.json'
$RdpNamespace = 'root/cimv2/TerminalServices'
$RdpFilter = "TerminalName='RDP-tcp'"
$WorkerCandidate = Join-Path ([IO.Path]::GetTempPath()) (
    "HermesRdpCertRotation-$([Guid]::NewGuid().ToString('N')).ps1"
)
$SyncCandidate = Join-Path ([IO.Path]::GetTempPath()) (
    "HermesRdpCertSync-$([Guid]::NewGuid().ToString('N')).ps1"
)

function Resolve-RepositorySha {
    param([string]$Ref)

    if ($Ref -match '^[0-9a-fA-F]{40}$') {
        return $Ref.ToLowerInvariant()
    }

    $Encoded = [Uri]::EscapeDataString($Ref)
    $Commit = Invoke-RestMethod `
        -UseBasicParsing `
        -Uri "https://api.github.com/repos/$Repo/commits/$Encoded" `
        -Headers @{ Accept = 'application/vnd.github+json' }

    $Sha = [string]$Commit.sha
    if ($Sha -notmatch '^[0-9a-fA-F]{40}$') {
        throw 'Не удалось разрешить RepositoryRef в immutable commit SHA.'
    }
    return $Sha.ToLowerInvariant()
}

function Assert-PowerShellFile {
    param([string]$Path)

    $Tokens = $null
    $Errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $Path,
        [ref]$Tokens,
        [ref]$Errors
    )
    if ($Errors.Count -gt 0) {
        throw "PowerShell parse error: $($Errors[0].Message)"
    }
}

function Set-SystemScriptAcl {
    param([string]$Path)

    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Normalize-Thumbprint {
    param([string]$Value)
    return (($Value -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
}

function Get-RdpSetting {
    return Get-CimInstance `
        -Namespace $RdpNamespace `
        -ClassName Win32_TSGeneralSetting `
        -Filter $RdpFilter
}

function Initialize-RdpOriginSnapshot {
    $Existing = Read-JsonFile -Path $OriginPath
    if ($Existing) {
        $ExistingThumbprint = Normalize-Thumbprint -Value ([string]$Existing.original_thumbprint)
        $ExistingType = [int]$Existing.original_hash_type
        if ($ExistingThumbprint.Length -ne 40 -or $ExistingType -notin @(1, 3)) {
            throw 'Сохранённый RDP origin snapshot повреждён.'
        }
        return 'PRESERVED'
    }

    $Source = 'CURRENT_LISTENER'
    $OriginalThumbprint = ''
    $OriginalType = 0

    $Legacy = Read-JsonFile -Path $LegacyBackupPath
    if ($Legacy) {
        $LegacyThumbprint = Normalize-Thumbprint -Value ([string]$Legacy.previous_thumbprint)
        $LegacyType = [int]$Legacy.previous_hash_type
        if ($LegacyThumbprint.Length -eq 40 -and $LegacyType -in @(1, 3)) {
            $OriginalThumbprint = $LegacyThumbprint
            $OriginalType = $LegacyType
            $Source = 'LEGACY_BACKUP'
        }
    }

    if (-not $OriginalThumbprint) {
        $Current = Get-RdpSetting
        $OriginalThumbprint = Normalize-Thumbprint -Value ([string]$Current.SSLCertificateSHA1Hash)
        $OriginalType = [int]$Current.SSLCertificateSHA1HashType
    }

    if ($OriginalThumbprint.Length -ne 40 -or $OriginalType -notin @(1, 3)) {
        throw 'Не удалось сохранить исходное состояние RDP certificate binding.'
    }

    $Temp = "$OriginPath.tmp"
    [ordered]@{
        captured_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        original_thumbprint = $OriginalThumbprint
        original_hash_type = $OriginalType
        source = $Source
    } |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $Temp -Encoding UTF8
    Move-Item -LiteralPath $Temp -Destination $OriginPath -Force
    Set-SystemScriptAcl -Path $OriginPath
    return $Source
}

function Get-NativePowerShellPath {
    $System32 = Join-Path $env:WINDIR 'System32'
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return Join-Path $System32 'WindowsPowerShell\v1.0\powershell.exe'
}

function Register-RotationTask {
    $Action = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument (
            '-NoProfile -ExecutionPolicy Bypass -File ' +
            "`"$WorkerPath`""
        )
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT45S'
    $Principal = New-ScheduledTaskPrincipal `
        -UserId 'SYSTEM' `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $Settings `
        -Force |
        Out-Null
}

function Get-PrincipalSid {
    param([string]$UserId)

    if ($UserId -match '^S-\d-') {
        return $UserId
    }
    try {
        return (
            New-Object System.Security.Principal.NTAccount($UserId)
        ).Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        return ''
    }
}

function Stop-RotationTaskBounded {
    $Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $Existing) {
        return
    }

    Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        $Current = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $Current -or [string]$Current.State -ne 'Running') {
            Start-Sleep -Milliseconds 500
            return
        }
        Start-Sleep -Milliseconds 250
    }

    throw 'Existing certificate rotation task did not stop within 10 seconds.'
}

Write-Host '=== CERT-012 ==='

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw 'Hermes device.json не найден. Сначала установите Hermes RDP client.'
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$WorkerUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/client/HermesRdpCertRotation.ps1"
)
$SyncUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/sync-rdp-certificate.ps1"
)

$BackupRoot = Join-Path $BaseDir 'backups\cert-rotation'
$BackupDir = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$WorkerExisted = Test-Path -LiteralPath $WorkerPath
$SyncExisted = Test-Path -LiteralPath $SyncPath
$TaskBefore = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$TaskExisted = $null -ne $TaskBefore
$TaskStateBefore = if ($TaskBefore) { [string]$TaskBefore.State } else { 'ABSENT' }
$TaskXmlBefore = if ($TaskBefore) { Export-ScheduledTask -TaskName $TaskName } else { $null }

if ($WorkerExisted) {
    Copy-Item -LiteralPath $WorkerPath -Destination (Join-Path $BackupDir 'HermesRdpCertRotation.ps1') -Force
}
if ($SyncExisted) {
    Copy-Item -LiteralPath $SyncPath -Destination (Join-Path $BackupDir 'sync-rdp-certificate.ps1') -Force
}
if ($TaskExisted) {
    $TaskXmlBefore | Set-Content -LiteralPath (Join-Path $BackupDir 'scheduled-task.xml') -Encoding UTF8
}

try {
    Invoke-WebRequest -UseBasicParsing -Uri $WorkerUrl -OutFile $WorkerCandidate
    Invoke-WebRequest -UseBasicParsing -Uri $SyncUrl -OutFile $SyncCandidate
    Assert-PowerShellFile -Path $WorkerCandidate
    Assert-PowerShellFile -Path $SyncCandidate

    if ($TaskExisted) {
        Stop-RotationTaskBounded
    }

    Copy-Item -LiteralPath $WorkerCandidate -Destination $WorkerPath -Force
    Copy-Item -LiteralPath $SyncCandidate -Destination $SyncPath -Force
    Set-SystemScriptAcl -Path $WorkerPath
    Set-SystemScriptAcl -Path $SyncPath

    $OriginState = Initialize-RdpOriginSnapshot

    $NativePowerShell = Get-NativePowerShellPath
    & $NativePowerShell `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $WorkerPath `
        -Once
    if ($LASTEXITCODE -ne 0) {
        throw "Initial certificate rotation check failed with code $LASTEXITCODE"
    }

    Register-RotationTask
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2

    $TaskAfter = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($TaskAfter.State -ne 'Running') {
        throw "Certificate rotation task did not enter Running state: $($TaskAfter.State)"
    }
    $TaskSid = Get-PrincipalSid -UserId ([string]$TaskAfter.Principal.UserId)
    if ($TaskSid -ne 'S-1-5-18') {
        throw (
            'Certificate rotation task is not LocalSystem: ' +
            "UserId=$($TaskAfter.Principal.UserId) SID=$TaskSid"
        )
    }

    Write-Host "RESOLVED_REF=$ResolvedSha"
    Write-Host "RDP_ORIGIN=$OriginState"
    Write-Host 'ROTATION_CHECK=PASS'
    Write-Host 'ROTATION_TASK=RUNNING'
    Write-Host 'ROTATION_TASK_SID=S-1-5-18'
    Write-Host "BACKUP=$BackupDir"
    Write-Host 'CERT-012_SETUP=PASS'
}
catch {
    $Failure = $_
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask `
        -TaskName $TaskName `
        -Confirm:$false `
        -ErrorAction SilentlyContinue

    if ($WorkerExisted) {
        Copy-Item `
            -LiteralPath (Join-Path $BackupDir 'HermesRdpCertRotation.ps1') `
            -Destination $WorkerPath `
            -Force
    }
    else {
        Remove-Item -LiteralPath $WorkerPath -Force -ErrorAction SilentlyContinue
    }

    if ($SyncExisted) {
        Copy-Item `
            -LiteralPath (Join-Path $BackupDir 'sync-rdp-certificate.ps1') `
            -Destination $SyncPath `
            -Force
    }
    else {
        Remove-Item -LiteralPath $SyncPath -Force -ErrorAction SilentlyContinue
    }

    if ($TaskExisted) {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Xml $TaskXmlBefore `
            -Force |
            Out-Null
        if ($TaskStateBefore -eq 'Running') {
            Start-ScheduledTask -TaskName $TaskName
        }
        elseif ($TaskStateBefore -eq 'Disabled') {
            Disable-ScheduledTask -TaskName $TaskName | Out-Null
        }
    }

    Write-Host 'CERT-012_SETUP_ROLLBACK=PASS'
    throw $Failure
}
finally {
    Remove-Item `
        -LiteralPath $WorkerCandidate, $SyncCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
