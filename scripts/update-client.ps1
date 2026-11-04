param([string]$RepositoryRef = 'main')
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$TaskName = 'Hermes RDP Agent'
$AgentPath = Join-Path $BaseDir 'HermesRdpAgent.ps1'
$ConfigPath = Join-Path $BaseDir 'device.json'
$ClientRefPath = Join-Path $BaseDir 'client-ref.txt'
$StartupTimeoutSeconds = 75
$StartupStableSeconds = 20
$CandidatePath = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpAgent-$([Guid]::NewGuid().ToString('N')).ps1")
$CertSetupCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpUpdateCertSetup-$([Guid]::NewGuid().ToString('N')).ps1")
$SmartRouteSetupCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("BakunityHostSmartRouteUpdate-$([Guid]::NewGuid().ToString('N')).ps1")

function Get-Sha256 {
    param([string]$Path)

    return (
        Get-FileHash `
            -LiteralPath $Path `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
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

function Write-ClientRef {
    param([string]$ResolvedSha)
    $Temp = "$ClientRefPath.tmp"
    Set-Content -LiteralPath $Temp -Value $ResolvedSha -Encoding ASCII
    $Acl = Get-Acl -LiteralPath $Temp
    $Acl.SetSecurityDescriptorSddlForm('O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Set-Acl -LiteralPath $Temp -AclObject $Acl
    Move-Item -LiteralPath $Temp -Destination $ClientRefPath -Force
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

function Invoke-CertificateRotationSetup {
    param(
        [string]$SetupPath,
        [string]$ResolvedSha
    )

    $NativePowerShell = Get-NativePowerShellPath
    & $NativePowerShell `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $SetupPath `
        -RepositoryRef $ResolvedSha
    if ($LASTEXITCODE -ne 0) {
        throw "Certificate rotation setup failed with code $LASTEXITCODE"
    }
}

function Invoke-OptionalHostSmartRouteSetup {
    param(
        [string]$SetupUrl,
        [string]$SetupPath,
        [string]$ResolvedSha
    )

    try {
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $SetupUrl `
            -OutFile $SetupPath
        Assert-PowerShellFile -Path $SetupPath
        $NativePowerShell = Get-NativePowerShellPath
        $Output = & $NativePowerShell `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $SetupPath `
            -RepositoryRef $ResolvedSha 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            throw "Host Smart Route setup failed with code $LASTEXITCODE. $($Output.Trim())"
        }
        if ($Output.Trim()) { Write-Host $Output.TrimEnd() }
        return $true
    }
    catch {
        Write-Warning (
            'Smart Route Host deferred; updated RDP remains healthy. ' +
            $_.Exception.Message
        )
        return $false
    }
}

function Get-HermesAgentProcesses {
    return @(
        Get-CimInstance `
            Win32_Process `
            -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($AgentPath)
        }
    )
}

function Get-HermesSshProcesses {
    param([string]$KeyPath)

    return @(
        Get-CimInstance `
            Win32_Process `
            -Filter "Name='ssh.exe'" `
            -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($KeyPath)
        }
    )
}

function Stop-HermesRuntime {
    param([string]$KeyPath)

    $Processes = @(
        @(Get-HermesAgentProcesses) +
        @(Get-HermesSshProcesses -KeyPath $KeyPath)
    ) |
        Sort-Object ProcessId -Unique

    foreach ($Process in $Processes) {
        Stop-Process `
            -Id ([int]$Process.ProcessId) `
            -Force `
            -ErrorAction SilentlyContinue
    }
}

function Get-StartupDetail {
    $Sections = @()
    foreach ($Item in @(
        @{ Name = 'agent.log'; Path = (Join-Path $BaseDir 'agent.log') },
        @{ Name = 'ssh-error.log'; Path = (Join-Path $BaseDir 'ssh-error.log') }
    )) {
        if (Test-Path -LiteralPath $Item.Path) {
            $Tail = (
                Get-Content `
                    -LiteralPath $Item.Path `
                    -Tail 20 `
                    -ErrorAction SilentlyContinue |
                    Out-String
            ).Trim()
            if ($Tail) {
                $Sections += "$($Item.Name):`n$Tail"
            }
        }
    }
    if ($Sections.Count -eq 0) {
        return 'agent.log/ssh-error.log ещё не созданы'
    }
    return ($Sections -join "`n")
}

function Wait-HermesRuntimeReady {
    param(
        [string]$KeyPath,
        [bool]$ExpectSsh,
        [int]$TimeoutSeconds,
        [int]$StableSeconds
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $StableSince = $null
    $StableAgentPid = 0
    $StableSshPid = 0

    while ([DateTime]::UtcNow -lt $Deadline) {
        $Task = Get-ScheduledTask `
            -TaskName $TaskName `
            -ErrorAction SilentlyContinue
        $Agents = @(Get-HermesAgentProcesses)
        $Ssh = @(Get-HermesSshProcesses -KeyPath $KeyPath)

        $RuntimeShapeOk = (
            $Task -and
            $Task.State -eq 'Running' -and
            $Agents.Count -eq 1 -and
            $Ssh.Count -le 1 -and
            (-not $ExpectSsh -or $Ssh.Count -eq 1)
        )

        if ($RuntimeShapeOk) {
            $AgentPid = [int]$Agents[0].ProcessId
            $SshPid = if ($Ssh.Count -eq 1) {
                [int]$Ssh[0].ProcessId
            }
            else {
                0
            }

            if (
                $StableAgentPid -ne $AgentPid -or
                $StableSshPid -ne $SshPid
            ) {
                $StableAgentPid = $AgentPid
                $StableSshPid = $SshPid
                $StableSince = [DateTime]::UtcNow
            }
            elseif (
                $StableSince -and
                (([DateTime]::UtcNow - $StableSince).TotalSeconds -ge $StableSeconds)
            ) {
                return @{
                    AgentPid = $AgentPid
                    SshPid = $SshPid
                    SshCount = $Ssh.Count
                }
            }
        }
        else {
            $StableSince = $null
            $StableAgentPid = 0
            $StableSshPid = 0
        }

        Start-Sleep -Seconds 1
    }

    $Detail = Get-StartupDetail
    throw (
        "Hermes runtime не вышел в стабильное состояние за " +
        "$TimeoutSeconds сек. $Detail"
    )
}

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

Write-Host '=== HERMES RDP TRANSACTIONAL UPDATE ===' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $AgentPath)) {
    throw 'Hermes RDP Agent не установлен.'
}
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw 'Конфигурация Hermes RDP не найдена.'
}

try {
    $Config = Get-Content `
        -LiteralPath $ConfigPath `
        -Raw |
        ConvertFrom-Json
}
catch {
    throw 'device.json повреждён или не читается.'
}

$KeyPath = [string]$Config.ssh_key_path
if ([string]::IsNullOrWhiteSpace($KeyPath)) {
    throw 'В device.json отсутствует ssh_key_path.'
}
if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw 'Приватный SSH-ключ Hermes не найден.'
}

$TaskBefore = Get-ScheduledTask `
    -TaskName $TaskName `
    -ErrorAction SilentlyContinue
if (-not $TaskBefore) {
    throw 'Scheduled Task Hermes RDP Agent не найден. Используйте repair flow.'
}
if ($TaskBefore.State -eq 'Disabled') {
    throw 'Scheduled Task Hermes RDP Agent отключён. Используйте repair flow.'
}

$AgentsBefore = @(Get-HermesAgentProcesses)
$SshBefore = @(Get-HermesSshProcesses -KeyPath $KeyPath)
if ($AgentsBefore.Count -ne 1) {
    throw (
        'Перед update ожидается ровно один Hermes Agent process; найдено ' +
        "$($AgentsBefore.Count). Используйте repair flow."
    )
}
if ($SshBefore.Count -gt 1) {
    throw (
        'Перед update обнаружено несколько Hermes ssh.exe. ' +
        'Используйте repair flow.'
    )
}

$ExpectSsh = $SshBefore.Count -eq 1
$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$CandidateUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/client/HermesRdpAgent.ps1"
)
$CertSetupUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/setup-client-cert-rotation.ps1"
)
$SmartRouteSetupUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/setup-smart-route-host.ps1"
)

try {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CandidateUrl `
        -OutFile $CandidatePath
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CertSetupUrl `
        -OutFile $CertSetupCandidate

    Assert-PowerShellFile -Path $CandidatePath
    Assert-PowerShellFile -Path $CertSetupCandidate

    $BackupRoot = Join-Path $BaseDir 'backups\updates'
    $BackupDir = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    New-Item `
        -ItemType Directory `
        -Path $BackupDir `
        -Force |
        Out-Null

    $BackupAgent = Join-Path $BackupDir 'HermesRdpAgent.ps1'
    $BackupTask = Join-Path $BackupDir 'scheduled-task.xml'
    $BackupMetadata = Join-Path $BackupDir 'update-metadata.json'

    Copy-Item `
        -LiteralPath $AgentPath `
        -Destination $BackupAgent `
        -Force

    Export-ScheduledTask -TaskName $TaskName |
        Set-Content `
            -LiteralPath $BackupTask `
            -Encoding UTF8

    [ordered]@{
        requested_ref = $RepositoryRef
        resolved_sha = $ResolvedSha
        previous_agent_sha256 = Get-Sha256 -Path $AgentPath
        candidate_agent_sha256 = Get-Sha256 -Path $CandidatePath
        candidate_cert_setup_sha256 = Get-Sha256 -Path $CertSetupCandidate
        task_state_before = [string]$TaskBefore.State
        expected_ssh_before = [bool]$ExpectSsh
    } |
        ConvertTo-Json -Depth 4 |
        Set-Content `
            -LiteralPath $BackupMetadata `
            -Encoding UTF8

    $MutationStarted = $false
    try {
        $MutationStarted = $true

        Stop-ScheduledTask `
            -TaskName $TaskName `
            -ErrorAction SilentlyContinue
        Stop-HermesRuntime -KeyPath $KeyPath

        Copy-Item `
            -LiteralPath $CandidatePath `
            -Destination $AgentPath `
            -Force

        Assert-PowerShellFile -Path $AgentPath

        Start-ScheduledTask -TaskName $TaskName
        $Ready = Wait-HermesRuntimeReady `
            -KeyPath $KeyPath `
            -ExpectSsh $ExpectSsh `
            -TimeoutSeconds $StartupTimeoutSeconds `
            -StableSeconds $StartupStableSeconds

        # The certificate setup is a transactional sub-operation. If it fails,
        # it restores its own files/task and throws; this outer update then
        # restores the previous main Agent/task below.
        Invoke-CertificateRotationSetup `
            -SetupPath $CertSetupCandidate `
            -ResolvedSha $ResolvedSha

        $SmartRouteManaged = Invoke-OptionalHostSmartRouteSetup `
            -SetupUrl $SmartRouteSetupUrl `
            -SetupPath $SmartRouteSetupCandidate `
            -ResolvedSha $ResolvedSha

        if ($SmartRouteManaged) {
            Write-ClientRef -ResolvedSha $ResolvedSha
        }

        Write-Host
        Write-Host 'UPDATE=PASS' -ForegroundColor Green
        Write-Host "ResolvedRef: $ResolvedSha"
        if ($SmartRouteManaged) {
            Write-Host "ClientRef: $ResolvedSha"
            Write-Host 'SmartRouteHost: managed'
        }
        else {
            Write-Host 'ClientRef: deferred until Smart Route Host setup succeeds' -ForegroundColor Yellow
            Write-Host 'SmartRouteHost: deferred' -ForegroundColor Yellow
        }
        Write-Host "Backup: $BackupDir"
        Write-Host "AgentPID: $($Ready.AgentPid)"
        Write-Host "HermesSshCount: $($Ready.SshCount)"
        Write-Host 'CertificateRotation: managed'
    }
    catch {
        $UpdateFailure = $_
        $RollbackOk = $true
        $RollbackDetail = $null

        try {
            Stop-ScheduledTask `
                -TaskName $TaskName `
                -ErrorAction SilentlyContinue
            Stop-HermesRuntime -KeyPath $KeyPath

            Copy-Item `
                -LiteralPath $BackupAgent `
                -Destination $AgentPath `
                -Force

            Start-ScheduledTask -TaskName $TaskName
            [void](Wait-HermesRuntimeReady `
                -KeyPath $KeyPath `
                -ExpectSsh $ExpectSsh `
                -TimeoutSeconds $StartupTimeoutSeconds `
                -StableSeconds $StartupStableSeconds)
        }
        catch {
            $RollbackOk = $false
            $RollbackDetail = $_.Exception.Message
        }

        if ($RollbackOk) {
            Write-Host 'ROLLBACK=PASS' -ForegroundColor Yellow
            Write-Host "Backup: $BackupDir"
            throw (
                'Обновление не применено; предыдущий агент восстановлен. ' +
                "Причина: $($UpdateFailure.Exception.Message)"
            )
        }

        Write-Host 'ROLLBACK=FAIL' -ForegroundColor Red
        Write-Host "Backup: $BackupDir"
        throw (
            'Update и автоматический rollback завершились ошибкой. ' +
            "Update: $($UpdateFailure.Exception.Message) " +
            "Rollback: $RollbackDetail"
        )
    }
}
finally {
    Remove-Item `
        -LiteralPath $CandidatePath, $CertSetupCandidate, $SmartRouteSetupCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
