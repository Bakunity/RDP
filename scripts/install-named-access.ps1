param(
    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$ApiFingerprint,

    [Parameter(Mandatory = $true)]
    [string]$AccessToken,

    [string]$RepositoryRef = 'main'
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\BakunityRDP\NamedAccess'
$WorkerPath = Join-Path $BaseDir 'BakunityNamedAccess.ps1'
$ConfigPath = Join-Path $BaseDir 'config.json'
$StatePath = Join-Path $BaseDir 'state.json'
$ClientRefPath = Join-Path $BaseDir 'client-ref.txt'
$TaskName = 'Bakunity RDP Named Access'
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$HostsBegin = '# BEGIN BAKUNITY RDP NAMED ACCESS'
$HostsEnd = '# END BAKUNITY RDP NAMED ACCESS'
$Candidate = Join-Path ([IO.Path]::GetTempPath()) (
    "BakunityNamedAccess-$([Guid]::NewGuid().ToString('N')).ps1"
)

function Resolve-RepositorySha {
    param([string]$Ref)
    if ($Ref -match '^[0-9a-fA-F]{40}$') {
        return $Ref.ToLowerInvariant()
    }
    $Encoded = [Uri]::EscapeDataString($Ref)
    $Commit = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repo/commits/$Encoded" -Headers @{ Accept = 'application/vnd.github+json' }
    $Sha = [string]$Commit.sha
    if ($Sha -notmatch '^[0-9a-fA-F]{40}$') {
        throw 'Unable to resolve RepositoryRef to an immutable commit SHA.'
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

function Set-SystemAdminAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
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

function Stop-TaskBounded {
    $Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $Existing) {
        return
    }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        $Current = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $Current -or [string]$Current.State -ne 'Running') {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'Existing Named Access task did not stop within 10 seconds.'
}

function Remove-ManagedHostsBlock {
    param([string]$Text)
    $Pattern = (
        '(?ms)^\s*' +
        [regex]::Escape($HostsBegin) +
        '\s*\r?\n.*?^\s*' +
        [regex]::Escape($HostsEnd) +
        '\s*(?:\r?\n)?'
    )
    return [regex]::Replace($Text, $Pattern, '')
}

function Cleanup-FreshNamedAccessRuntime {
    $System32 = Join-Path $env:WINDIR 'System32'
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    $Netsh = Join-Path $System32 'netsh.exe'
    $Ipconfig = Join-Path $System32 'ipconfig.exe'

    if (Test-Path -LiteralPath $StatePath) {
        try {
            $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
            if ($State -and $State.mappings) {
                foreach ($Property in $State.mappings.PSObject.Properties) {
                    $Address = [string]$Property.Value.loopback
                    if ($Address -match '^127\.77\.\d{1,3}\.\d{1,3}$') {
                        & $Netsh interface portproxy delete v4tov4 listenaddress=$Address listenport=3389 protocol=tcp *> $null
                    }
                }
            }
        }
        catch {
        }
    }

    if (Test-Path -LiteralPath $HostsPath) {
        try {
            $Original = [IO.File]::ReadAllText($HostsPath)
            $Clean = Remove-ManagedHostsBlock -Text $Original
            if ($Clean -ne $Original) {
                [IO.File]::WriteAllText(
                    $HostsPath,
                    $Clean.TrimEnd([char]13, [char]10) + [Environment]::NewLine,
                    (New-Object Text.UTF8Encoding($false))
                )
                & $Ipconfig /flushdns | Out-Null
            }
        }
        catch {
        }
    }
}

$ApiBaseUrl = $ApiBaseUrl.TrimEnd('/')
if ($ApiBaseUrl -notmatch '^https://') {
    throw 'ApiBaseUrl must use HTTPS.'
}
$Fingerprint = (($ApiFingerprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
if ($Fingerprint.Length -ne 64) {
    throw 'ApiFingerprint must be a SHA-256 fingerprint.'
}
if ([string]::IsNullOrWhiteSpace($AccessToken)) {
    throw 'AccessToken is required.'
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$WorkerUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/client/BakunityNamedAccess.ps1"
)

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$ExistingTaskXml = if ($ExistingTask) {
    Export-ScheduledTask -TaskName $TaskName
}
else {
    $null
}
$ExistingWorker = if (Test-Path -LiteralPath $WorkerPath) {
    Get-Content -LiteralPath $WorkerPath -Raw
}
else {
    $null
}
$ExistingConfig = if (Test-Path -LiteralPath $ConfigPath) {
    Get-Content -LiteralPath $ConfigPath -Raw
}
else {
    $null
}
$ExistingClientRef = if (Test-Path -LiteralPath $ClientRefPath) {
    Get-Content -LiteralPath $ClientRefPath -Raw
}
else {
    $null
}

try {
    Invoke-WebRequest -UseBasicParsing -Uri $WorkerUrl -OutFile $Candidate
    Assert-PowerShellFile -Path $Candidate

    New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
    Stop-TaskBounded
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    Copy-Item -LiteralPath $Candidate -Destination $WorkerPath -Force
    Set-SystemAdminAcl -Path $WorkerPath

    [ordered]@{
        api_base_url = $ApiBaseUrl
        api_fingerprint = $Fingerprint
        access_token = $AccessToken
        repository_ref = $ResolvedSha
        installed_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    } |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $ConfigPath -Encoding UTF8
    Set-SystemAdminAcl -Path $ConfigPath

    Set-Content -LiteralPath $ClientRefPath -Value $ResolvedSha -Encoding ASCII
    Set-SystemAdminAcl -Path $ClientRefPath

    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        '-NoProfile -ExecutionPolicy Bypass -File ' +
        '"' + $WorkerPath + '"'
    )
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT30S'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

    $NativePowerShell = Get-NativePowerShellPath
    $Output = @(
        & $NativePowerShell -NoProfile -ExecutionPolicy Bypass -File $WorkerPath -Once 2>&1
    )
    $Exit = $LASTEXITCODE
    foreach ($Line in $Output) {
        if ($Line) {
            Write-Host ([string]$Line)
        }
    }
    if ($Exit -ne 0) {
        throw "Initial Named Access sync failed with code $Exit"
    }

    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($Task.State -ne 'Running') {
        throw "Named Access task did not enter Running state: $($Task.State)"
    }

    Write-Host "RESOLVED_REF=$ResolvedSha"
    Write-Host "TASK=$TaskName"
    Write-Host "CONFIG=$ConfigPath"
    Write-Host 'NAMED_ACCESS_INSTALL=PASS' -ForegroundColor Green
}
catch {
    $Failure = $_
    try {
        Stop-TaskBounded
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

        if ($null -ne $ExistingWorker) {
            Set-Content -LiteralPath $WorkerPath -Value $ExistingWorker -Encoding UTF8
            Set-SystemAdminAcl -Path $WorkerPath
        }
        else {
            Remove-Item -LiteralPath $WorkerPath -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $ExistingConfig) {
            Set-Content -LiteralPath $ConfigPath -Value $ExistingConfig -Encoding UTF8
            Set-SystemAdminAcl -Path $ConfigPath
        }
        else {
            Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $ExistingClientRef) {
            Set-Content -LiteralPath $ClientRefPath -Value $ExistingClientRef -Encoding ASCII
            Set-SystemAdminAcl -Path $ClientRefPath
        }
        else {
            Remove-Item -LiteralPath $ClientRefPath -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $ExistingWorker -and $null -ne $ExistingConfig) {
            $RollbackPowerShell = Get-NativePowerShellPath
            & $RollbackPowerShell -NoProfile -ExecutionPolicy Bypass -File $WorkerPath -Once *> $null
        }
        else {
            Cleanup-FreshNamedAccessRuntime
            Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
        }

        if ($ExistingTaskXml) {
            Register-ScheduledTask -TaskName $TaskName -Xml $ExistingTaskXml -Force | Out-Null
            Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        }
    }
    catch {
        Write-Host "INSTALL_ROLLBACK=ERROR:$($_.Exception.Message)" -ForegroundColor Yellow
    }
    throw $Failure
}
finally {
    Remove-Item -LiteralPath $Candidate -Force -ErrorAction SilentlyContinue
}
) {
                        & $Netsh interface portproxy delete v4tov4 listenaddress=$Address listenport=3389 protocol=tcp *> $null
                    }
                }
            }
        }
        catch {
        }
    }

    if (Test-Path -LiteralPath $HostsPath) {
        try {
            $Original = [IO.File]::ReadAllText($HostsPath)
            $Clean = Remove-ManagedHostsBlock -Text $Original
            if ($Clean -ne $Original) {
                [IO.File]::WriteAllText(
                    $HostsPath,
                    $Clean.TrimEnd([char]13, [char]10) + [Environment]::NewLine,
                    (New-Object Text.UTF8Encoding($false))
                )
                & $Ipconfig /flushdns | Out-Null
            }
        }
        catch {
        }
    }
}

$ApiBaseUrl = $ApiBaseUrl.TrimEnd('/')
if ($ApiBaseUrl -notmatch '^https://') {
    throw 'ApiBaseUrl must use HTTPS.'
}
$Fingerprint = (($ApiFingerprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
if ($Fingerprint.Length -ne 64) {
    throw 'ApiFingerprint must be a SHA-256 fingerprint.'
}
if ([string]::IsNullOrWhiteSpace($AccessToken)) {
    throw 'AccessToken is required.'
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$WorkerUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/client/BakunityNamedAccess.ps1"
)

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$ExistingTaskXml = if ($ExistingTask) {
    Export-ScheduledTask -TaskName $TaskName
}
else {
    $null
}
$ExistingWorker = if (Test-Path -LiteralPath $WorkerPath) {
    Get-Content -LiteralPath $WorkerPath -Raw
}
else {
    $null
}
$ExistingConfig = if (Test-Path -LiteralPath $ConfigPath) {
    Get-Content -LiteralPath $ConfigPath -Raw
}
else {
    $null
}

try {
    Invoke-WebRequest -UseBasicParsing -Uri $WorkerUrl -OutFile $Candidate
    Assert-PowerShellFile -Path $Candidate

    New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
    Stop-TaskBounded
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    Copy-Item -LiteralPath $Candidate -Destination $WorkerPath -Force
    Set-SystemAdminAcl -Path $WorkerPath

    [ordered]@{
        api_base_url = $ApiBaseUrl
        api_fingerprint = $Fingerprint
        access_token = $AccessToken
        repository_ref = $ResolvedSha
        installed_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    } |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $ConfigPath -Encoding UTF8
    Set-SystemAdminAcl -Path $ConfigPath

    Set-Content -LiteralPath $ClientRefPath -Value $ResolvedSha -Encoding ASCII
    Set-SystemAdminAcl -Path $ClientRefPath

    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        '-NoProfile -ExecutionPolicy Bypass -File ' +
        '"' + $WorkerPath + '"'
    )
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT30S'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

    $NativePowerShell = Get-NativePowerShellPath
    $Output = @(
        & $NativePowerShell -NoProfile -ExecutionPolicy Bypass -File $WorkerPath -Once 2>&1
    )
    $Exit = $LASTEXITCODE
    foreach ($Line in $Output) {
        if ($Line) {
            Write-Host ([string]$Line)
        }
    }
    if ($Exit -ne 0) {
        throw "Initial Named Access sync failed with code $Exit"
    }

    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($Task.State -ne 'Running') {
        throw "Named Access task did not enter Running state: $($Task.State)"
    }

    Write-Host "RESOLVED_REF=$ResolvedSha"
    Write-Host "TASK=$TaskName"
    Write-Host "CONFIG=$ConfigPath"
    Write-Host 'NAMED_ACCESS_INSTALL=PASS' -ForegroundColor Green
}
catch {
    $Failure = $_
    try {
        Stop-TaskBounded
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

        if ($null -ne $ExistingWorker) {
            Set-Content -LiteralPath $WorkerPath -Value $ExistingWorker -Encoding UTF8
            Set-SystemAdminAcl -Path $WorkerPath
        }
        else {
            Remove-Item -LiteralPath $WorkerPath -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $ExistingConfig) {
            Set-Content -LiteralPath $ConfigPath -Value $ExistingConfig -Encoding UTF8
            Set-SystemAdminAcl -Path $ConfigPath
        }
        else {
            Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
        }

        if ($ExistingTaskXml) {
            Register-ScheduledTask -TaskName $TaskName -Xml $ExistingTaskXml -Force | Out-Null
            Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        }
    }
    catch {
        Write-Host "INSTALL_ROLLBACK=ERROR:$($_.Exception.Message)" -ForegroundColor Yellow
    }
    throw $Failure
}
finally {
    Remove-Item -LiteralPath $Candidate -Force -ErrorAction SilentlyContinue
}
