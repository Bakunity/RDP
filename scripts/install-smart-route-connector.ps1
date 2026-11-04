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
$BaseDir = 'C:\ProgramData\BakunityRDP\SmartRoute'
$WorkerPath = Join-Path $BaseDir 'BakunitySmartRoute.ps1'
$LauncherPath = Join-Path $BaseDir 'BakunitySmartRouteLaunch.ps1'
$MeshLibPath = Join-Path $BaseDir 'BakunityMesh.ps1'
$NativeTransportLibPath = Join-Path $BaseDir 'BakunityNativeTransport.ps1'
$ConfigPath = Join-Path $BaseDir 'config.json'
$StatePath = Join-Path $BaseDir 'state.json'
$ClientRefPath = Join-Path $BaseDir 'client-ref.txt'
$TaskName = 'Bakunity RDP Smart Route'
$ShortcutPath = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Bakunity RDP.lnk'
$Candidate = Join-Path ([IO.Path]::GetTempPath()) ("BakunitySmartRoute-$([Guid]::NewGuid().ToString('N')).ps1")
$LauncherCandidate = Join-Path ([IO.Path]::GetTempPath()) ("BakunitySmartRouteLaunch-$([Guid]::NewGuid().ToString('N')).ps1")
$MeshCandidate = Join-Path ([IO.Path]::GetTempPath()) ("BakunityMesh-$([Guid]::NewGuid().ToString('N')).ps1")
$NativeTransportCandidate = Join-Path ([IO.Path]::GetTempPath()) ("BakunityNativeTransport-$([Guid]::NewGuid().ToString('N')).ps1")

function Resolve-RepositorySha {
    param([string]$Ref)
    if ($Ref -match '^[0-9a-fA-F]{40}$') { return $Ref.ToLowerInvariant() }
    $Encoded = [Uri]::EscapeDataString($Ref)
    $Commit = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repo/commits/$Encoded" -Headers @{ Accept='application/vnd.github+json' }
    $Sha = [string]$Commit.sha
    if ($Sha -notmatch '^[0-9a-fA-F]{40}$') { throw 'Unable to resolve RepositoryRef.' }
    return $Sha.ToLowerInvariant()
}

function Assert-PowerShellFile {
    param([string]$Path)
    $Tokens = $null
    $Errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($Path, [ref]$Tokens, [ref]$Errors)
    if ($Errors.Count -gt 0) { throw "PowerShell parse error: $($Errors[0].Message)" }
}

function Set-SystemAdminAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Set-UserReadableAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)')
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Get-NativePowerShellPath {
    $System32 = Join-Path $env:WINDIR 'System32'
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) { $System32 = Join-Path $env:WINDIR 'Sysnative' }
    return Join-Path $System32 'WindowsPowerShell\v1.0\powershell.exe'
}

function Stop-TaskBounded {
    param([string]$Name)
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $Task) { return }
    Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    for ($i=0; $i -lt 40; $i++) {
        $Current = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if (-not $Current -or [string]$Current.State -ne 'Running') { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Scheduled Task did not stop: $Name"
}

function Install-LauncherShortcut {
    $PowerShell = Get-NativePowerShellPath
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $PowerShell
    $Shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $LauncherPath + '"'
    $Shortcut.WorkingDirectory = $BaseDir
    $Shortcut.Description = 'Bakunity RDP Smart Route'
    $Shortcut.Save()
}

$ApiBaseUrl = $ApiBaseUrl.TrimEnd('/')
if ($ApiBaseUrl -notmatch '^https://') { throw 'ApiBaseUrl must use HTTPS.' }
$Fingerprint = (($ApiFingerprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
if ($Fingerprint.Length -ne 64) { throw 'ApiFingerprint must be SHA-256.' }
if ([string]::IsNullOrWhiteSpace($AccessToken)) { throw 'AccessToken is required.' }

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$WorkerUrl = "https://raw.githubusercontent.com/$Repo/$ResolvedSha/client/BakunitySmartRoute.ps1"
$LauncherUrl = "https://raw.githubusercontent.com/$Repo/$ResolvedSha/client/BakunitySmartRouteLaunch.ps1"
$MeshUrl = "https://raw.githubusercontent.com/$Repo/$ResolvedSha/client/BakunityMesh.ps1"
$NativeTransportUrl = "https://raw.githubusercontent.com/$Repo/$ResolvedSha/client/BakunityNativeTransport.ps1"

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$ExistingTaskXml = if ($ExistingTask) { Export-ScheduledTask -TaskName $TaskName } else { $null }
$ExistingConfig = if (Test-Path -LiteralPath $ConfigPath) { Get-Content -LiteralPath $ConfigPath -Raw } else { $null }
$ExistingWorker = if (Test-Path -LiteralPath $WorkerPath) { Get-Content -LiteralPath $WorkerPath -Raw } else { $null }
$ExistingLauncher = if (Test-Path -LiteralPath $LauncherPath) { Get-Content -LiteralPath $LauncherPath -Raw } else { $null }
$ExistingMeshLib = if (Test-Path -LiteralPath $MeshLibPath) { Get-Content -LiteralPath $MeshLibPath -Raw } else { $null }
$ExistingNativeTransportLib = if (Test-Path -LiteralPath $NativeTransportLibPath) { Get-Content -LiteralPath $NativeTransportLibPath -Raw } else { $null }
$ExistingRef = if (Test-Path -LiteralPath $ClientRefPath) { Get-Content -LiteralPath $ClientRefPath -Raw } else { $null }

try {
    Invoke-WebRequest -UseBasicParsing -Uri $WorkerUrl -OutFile $Candidate
    Invoke-WebRequest -UseBasicParsing -Uri $LauncherUrl -OutFile $LauncherCandidate
    Invoke-WebRequest -UseBasicParsing -Uri $MeshUrl -OutFile $MeshCandidate
    Invoke-WebRequest -UseBasicParsing -Uri $NativeTransportUrl -OutFile $NativeTransportCandidate
    Assert-PowerShellFile -Path $Candidate
    Assert-PowerShellFile -Path $LauncherCandidate
    Assert-PowerShellFile -Path $MeshCandidate
    Assert-PowerShellFile -Path $NativeTransportCandidate

    New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
    Stop-TaskBounded -Name $TaskName
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    Copy-Item -LiteralPath $Candidate -Destination $WorkerPath -Force
    Set-SystemAdminAcl -Path $WorkerPath
    Copy-Item -LiteralPath $LauncherCandidate -Destination $LauncherPath -Force
    Set-UserReadableAcl -Path $LauncherPath
    Copy-Item -LiteralPath $MeshCandidate -Destination $MeshLibPath -Force
    Set-SystemAdminAcl -Path $MeshLibPath
    Copy-Item -LiteralPath $NativeTransportCandidate -Destination $NativeTransportLibPath -Force
    Set-SystemAdminAcl -Path $NativeTransportLibPath

    [ordered]@{
        api_base_url=$ApiBaseUrl
        api_fingerprint=$Fingerprint
        access_token=$AccessToken
        repository_ref=$ResolvedSha
        installed_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
    Set-SystemAdminAcl -Path $ConfigPath

    Set-Content -LiteralPath $ClientRefPath -Value $ResolvedSha -Encoding ASCII
    Set-SystemAdminAcl -Path $ClientRefPath

    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $WorkerPath + '"')
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT20S'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

    $NativePowerShell = Get-NativePowerShellPath
    $Output = @(& $NativePowerShell -NoProfile -ExecutionPolicy Bypass -File $WorkerPath -Once 2>&1)
    $Exit = $LASTEXITCODE
    foreach ($Line in $Output) { if ($Line) { Write-Host ([string]$Line) } }
    if ($Exit -ne 0) { throw "Initial Smart Route sync failed with code $Exit" }

    Install-LauncherShortcut
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ([string]$Task.State -ne 'Running') { throw "Smart Route task did not enter Running state: $($Task.State)" }

    Write-Host "RESOLVED_REF=$ResolvedSha"
    Write-Host "TASK=$TaskName"
    Write-Host "CONFIG=$ConfigPath"
    Write-Host "LAUNCHER=$ShortcutPath"
    Write-Host 'SMART_ROUTE_INSTALL=PASS' -ForegroundColor Green
}
catch {
    $Failure = $_
    try {
        Stop-TaskBounded -Name $TaskName
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        if ($null -ne $ExistingWorker) {
            Set-Content -LiteralPath $WorkerPath -Value $ExistingWorker -Encoding UTF8
            Set-SystemAdminAcl -Path $WorkerPath
        } else { Remove-Item -LiteralPath $WorkerPath -Force -ErrorAction SilentlyContinue }
        if ($null -ne $ExistingLauncher) {
            Set-Content -LiteralPath $LauncherPath -Value $ExistingLauncher -Encoding UTF8
            Set-UserReadableAcl -Path $LauncherPath
        } else { Remove-Item -LiteralPath $LauncherPath -Force -ErrorAction SilentlyContinue }
        if ($null -ne $ExistingMeshLib) {
            Set-Content -LiteralPath $MeshLibPath -Value $ExistingMeshLib -Encoding UTF8
            Set-SystemAdminAcl -Path $MeshLibPath
        } else { Remove-Item -LiteralPath $MeshLibPath -Force -ErrorAction SilentlyContinue }
        if ($null -ne $ExistingNativeTransportLib) {
            Set-Content -LiteralPath $NativeTransportLibPath -Value $ExistingNativeTransportLib -Encoding UTF8
            Set-SystemAdminAcl -Path $NativeTransportLibPath
        } else { Remove-Item -LiteralPath $NativeTransportLibPath -Force -ErrorAction SilentlyContinue }
        if ($null -ne $ExistingConfig) {
            Set-Content -LiteralPath $ConfigPath -Value $ExistingConfig -Encoding UTF8
            Set-SystemAdminAcl -Path $ConfigPath
        } else { Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue }
        if ($null -ne $ExistingRef) {
            Set-Content -LiteralPath $ClientRefPath -Value $ExistingRef -Encoding ASCII
            Set-SystemAdminAcl -Path $ClientRefPath
        } else { Remove-Item -LiteralPath $ClientRefPath -Force -ErrorAction SilentlyContinue }
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
    Remove-Item -LiteralPath $Candidate,$LauncherCandidate,$MeshCandidate,$NativeTransportCandidate -Force -ErrorAction SilentlyContinue
}
