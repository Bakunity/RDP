param(
    [string]$RepositoryRef = 'main',
    [string]$ExpectedDeviceId = ''
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$TaskName = 'Hermes RDP Agent'
$AgentPath = Join-Path $BaseDir 'HermesRdpAgent.ps1'
$ClientRefPath = Join-Path $BaseDir 'client-ref.txt'
$CoreCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpRepairCore-$([Guid]::NewGuid().ToString('N')).ps1")
$CertSetupCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpRepairCertSetup-$([Guid]::NewGuid().ToString('N')).ps1")

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

function Stop-MainRuntime {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq 'ssh.exe' -and $_.CommandLine -and
                $_.CommandLine.Contains('HermesRDP')) -or
            ($_.CommandLine -and $_.CommandLine.Contains($AgentPath))
        } |
        ForEach-Object {
            Stop-Process `
                -Id ([int]$_.ProcessId) `
                -Force `
                -ErrorAction SilentlyContinue
        }
}

function Restore-MainSnapshot {
    param(
        [bool]$AgentExisted,
        [string]$BackupAgent,
        [bool]$TaskExisted,
        [string]$TaskXml,
        [string]$TaskState
    )

    Stop-MainRuntime
    Unregister-ScheduledTask `
        -TaskName $TaskName `
        -Confirm:$false `
        -ErrorAction SilentlyContinue

    if ($AgentExisted) {
        Copy-Item `
            -LiteralPath $BackupAgent `
            -Destination $AgentPath `
            -Force
    }
    else {
        Remove-Item `
            -LiteralPath $AgentPath `
            -Force `
            -ErrorAction SilentlyContinue
    }

    if ($TaskExisted) {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Xml $TaskXml `
            -Force |
            Out-Null

        if ($TaskState -eq 'Running') {
            Start-ScheduledTask -TaskName $TaskName
        }
        elseif ($TaskState -eq 'Disabled') {
            Disable-ScheduledTask -TaskName $TaskName | Out-Null
        }
        else {
            Stop-ScheduledTask `
                -TaskName $TaskName `
                -ErrorAction SilentlyContinue
        }
    }
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$CoreUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/repair-client-core.ps1"
)
$CertSetupUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/setup-client-cert-rotation.ps1"
)
$NativePowerShell = Get-NativePowerShellPath

try {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CoreUrl `
        -OutFile $CoreCandidate
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CertSetupUrl `
        -OutFile $CertSetupCandidate
    Assert-PowerShellFile -Path $CoreCandidate
    Assert-PowerShellFile -Path $CertSetupCandidate

    $TaskBefore = Get-ScheduledTask `
        -TaskName $TaskName `
        -ErrorAction SilentlyContinue
    $TaskExistedBefore = $null -ne $TaskBefore
    $TaskStateBefore = if ($TaskBefore) {
        [string]$TaskBefore.State
    }
    else {
        'ABSENT'
    }
    $TaskXmlBefore = if ($TaskBefore) {
        Export-ScheduledTask -TaskName $TaskName
    }
    else {
        $null
    }
    $AgentExistedBefore = Test-Path -LiteralPath $AgentPath

    $BackupRoot = Join-Path $BaseDir 'backups\repair-lifecycle'
    $BackupDir = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $BackupAgent = Join-Path $BackupDir 'HermesRdpAgent.ps1'
    if ($AgentExistedBefore) {
        Copy-Item `
            -LiteralPath $AgentPath `
            -Destination $BackupAgent `
            -Force
    }
    if ($TaskExistedBefore) {
        $TaskXmlBefore |
            Set-Content `
                -LiteralPath (Join-Path $BackupDir 'scheduled-task.xml') `
                -Encoding UTF8
    }

    $CoreArgs = @(
        '-NoProfile'
        '-ExecutionPolicy'
        'Bypass'
        '-File'
        $CoreCandidate
        '-RepositoryRef'
        $ResolvedSha
    )
    if (-not [string]::IsNullOrWhiteSpace($ExpectedDeviceId)) {
        $CoreArgs += @('-ExpectedDeviceId', $ExpectedDeviceId)
    }

    $CoreOutput = & $NativePowerShell @CoreArgs 2>&1 | Out-String
    $CoreExit = $LASTEXITCODE
    if ($CoreExit -ne 0) {
        if ($CoreOutput.Trim()) {
            Write-Host $CoreOutput.TrimEnd()
        }
        throw "Repair core failed with code $CoreExit"
    }

    try {
        $CertOutput = & $NativePowerShell `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $CertSetupCandidate `
            -RepositoryRef $ResolvedSha 2>&1 |
            Out-String
        $CertExit = $LASTEXITCODE
        if ($CertExit -ne 0) {
            throw "Certificate rotation setup failed with code $CertExit. $($CertOutput.Trim())"
        }
    }
    catch {
        $CertFailure = $_
        $RollbackOk = $true
        $RollbackDetail = ''
        try {
            Restore-MainSnapshot `
                -AgentExisted $AgentExistedBefore `
                -BackupAgent $BackupAgent `
                -TaskExisted $TaskExistedBefore `
                -TaskXml $TaskXmlBefore `
                -TaskState $TaskStateBefore
        }
        catch {
            $RollbackOk = $false
            $RollbackDetail = $_.Exception.Message
        }

        if ($RollbackOk) {
            Write-Host 'CERT-013_REPAIR_ROLLBACK=PASS' -ForegroundColor Yellow
            throw (
                'Repair lifecycle не применён; main Agent/task snapshot ' +
                "восстановлен. Причина: $($CertFailure.Exception.Message)"
            )
        }

        Write-Host 'CERT-013_REPAIR_ROLLBACK=FAIL' -ForegroundColor Red
        throw (
            'Certificate lifecycle и outer rollback завершились ошибкой. ' +
            "Certificate: $($CertFailure.Exception.Message) " +
            "Rollback: $RollbackDetail"
        )
    }

    if ($CoreOutput.Trim()) {
        Write-Host $CoreOutput.TrimEnd()
    }
    Write-ClientRef -ResolvedSha $ResolvedSha
    Write-Host 'CertificateRotation: managed'
    Write-Host "ClientRef: $ResolvedSha"
    Write-Host 'CERT-013_REPAIR=PASS' -ForegroundColor Green
}
finally {
    Remove-Item `
        -LiteralPath $CoreCandidate, $CertSetupCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
