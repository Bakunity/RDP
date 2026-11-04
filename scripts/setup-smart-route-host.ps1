param([string]$RepositoryRef = 'main')

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$HermesDir = 'C:\ProgramData\HermesRDP'
$BaseDir = Join-Path $HermesDir 'SmartRoute'
$TaskName = 'Bakunity RDP Host Smart Route'
$WorkerPath = Join-Path $BaseDir 'BakunityHostSmartRoute.ps1'
$MeshLibPath = Join-Path $BaseDir 'BakunityMesh.ps1'
$RefPath = Join-Path $BaseDir 'client-ref.txt'
$ConfigPath = Join-Path $HermesDir 'device.json'

function Resolve-RepositorySha {
    param([string]$Ref)
    if ($Ref -match '^[0-9a-fA-F]{40}$') {
        return $Ref.ToLowerInvariant()
    }
    $Encoded = [Uri]::EscapeDataString($Ref)
    $Commit = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repo/commits/$Encoded" -Headers @{ Accept='application/vnd.github+json' }
    $Sha = [string]$Commit.sha
    if ($Sha -notmatch '^[0-9a-fA-F]{40}$') {
        throw 'Unable to resolve RepositoryRef.'
    }
    return $Sha.ToLowerInvariant()
}

function Assert-PowerShellFile {
    param([string]$Path)
    $Tokens = $null
    $Errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $Path, [ref]$Tokens, [ref]$Errors
    )
    if ($Errors.Count -gt 0) {
        throw "PowerShell parse error: $($Errors[0].Message)"
    }
}

function Set-SystemAdminAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'D:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Get-NativePowerShell {
    $System32 = Join-Path $env:WINDIR 'System32'
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return Join-Path $System32 'WindowsPowerShell\v1.0\powershell.exe'
}

function Stop-TaskBounded {
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $Task) { return }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    for ($i=0; $i -lt 40; $i++) {
        $Current = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $Current -or [string]$Current.State -ne 'Running') { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Scheduled Task did not stop: $TaskName"
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw 'Bakunity RDP Host is not installed.'
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$WorkerCandidate = Join-Path ([IO.Path]::GetTempPath()) ("BakunityHostSmartRoute-$([Guid]::NewGuid().ToString('N')).ps1")
$LibCandidate = Join-Path ([IO.Path]::GetTempPath()) ("BakunityMesh-$([Guid]::NewGuid().ToString('N')).ps1")
$WorkerUrl = "https://raw.githubusercontent.com/$Repo/$ResolvedSha/client/BakunityHostSmartRoute.ps1"
$LibUrl = "https://raw.githubusercontent.com/$Repo/$ResolvedSha/client/BakunityMesh.ps1"

$OldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$OldTaskXml = if ($OldTask) { Export-ScheduledTask -TaskName $TaskName } else { $null }
$OldWorker = if (Test-Path -LiteralPath $WorkerPath) { Get-Content -LiteralPath $WorkerPath -Raw } else { $null }
$OldLib = if (Test-Path -LiteralPath $MeshLibPath) { Get-Content -LiteralPath $MeshLibPath -Raw } else { $null }
$OldRef = if (Test-Path -LiteralPath $RefPath) { Get-Content -LiteralPath $RefPath -Raw } else { $null }

try {
    Invoke-WebRequest -UseBasicParsing -Uri $WorkerUrl -OutFile $WorkerCandidate
    Invoke-WebRequest -UseBasicParsing -Uri $LibUrl -OutFile $LibCandidate
    Assert-PowerShellFile -Path $WorkerCandidate
    Assert-PowerShellFile -Path $LibCandidate

    New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
    Stop-TaskBounded
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    Copy-Item -LiteralPath $WorkerCandidate -Destination $WorkerPath -Force
    Copy-Item -LiteralPath $LibCandidate -Destination $MeshLibPath -Force
    Set-SystemAdminAcl -Path $WorkerPath
    Set-SystemAdminAcl -Path $MeshLibPath
    Set-Content -LiteralPath $RefPath -Value $ResolvedSha -Encoding ASCII
    Set-SystemAdminAcl -Path $RefPath

    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $WorkerPath + '"')
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT25S'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

    $PowerShell = Get-NativePowerShell
    $Output = @(& $PowerShell -NoProfile -ExecutionPolicy Bypass -File $WorkerPath -Once 2>&1)
    $ExitCode = $LASTEXITCODE
    foreach ($Line in $Output) {
        if ($Line) { Write-Host ([string]$Line) }
    }
    if ($ExitCode -ne 0) {
        throw "Initial Host Smart Route sync failed with code $ExitCode"
    }

    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $Current = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ([string]$Current.State -ne 'Running') {
        throw "Host Smart Route task is not running: $($Current.State)"
    }

    Write-Host "HOST_SMART_ROUTE_REF=$ResolvedSha"
    Write-Host "HOST_SMART_ROUTE_TASK=$TaskName"
    Write-Host 'HOST_SMART_ROUTE_SETUP=PASS' -ForegroundColor Green
}
catch {
    $Failure = $_
    try {
        Stop-TaskBounded
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

        if ($null -ne $OldWorker) {
            Set-Content -LiteralPath $WorkerPath -Value $OldWorker -Encoding UTF8
            Set-SystemAdminAcl -Path $WorkerPath
        } else {
            Remove-Item -LiteralPath $WorkerPath -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $OldLib) {
            Set-Content -LiteralPath $MeshLibPath -Value $OldLib -Encoding UTF8
            Set-SystemAdminAcl -Path $MeshLibPath
        } else {
            Remove-Item -LiteralPath $MeshLibPath -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $OldRef) {
            Set-Content -LiteralPath $RefPath -Value $OldRef -Encoding ASCII
            Set-SystemAdminAcl -Path $RefPath
        } else {
            Remove-Item -LiteralPath $RefPath -Force -ErrorAction SilentlyContinue
        }

        if ($OldTaskXml) {
            Register-ScheduledTask -TaskName $TaskName -Xml $OldTaskXml -Force | Out-Null
            Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        }
    }
    catch {
        Write-Host "HOST_SMART_ROUTE_ROLLBACK=ERROR:$($_.Exception.Message)" -ForegroundColor Yellow
    }
    throw $Failure
}
finally {
    Remove-Item -LiteralPath $WorkerCandidate,$LibCandidate -Force -ErrorAction SilentlyContinue
}
