param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('repair', 'update')]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$RepositoryRef,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedDeviceId
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$ConfigPath = Join-Path $BaseDir 'device.json'
$ClientRefPath = Join-Path $BaseDir 'client-ref.txt'
$StatusPath = Join-Path $BaseDir 'maintenance-status.json'
$ActivePath = Join-Path $BaseDir 'maintenance-active.json'
$Candidate = Join-Path ([IO.Path]::GetTempPath()) ("HermesRdpMaintenance-$Action-$([Guid]::NewGuid().ToString('N')).ps1")

function Write-JsonAtomic {
    param([string]$Path, [object]$Value)
    $Temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Temp -Encoding UTF8
    Move-Item -LiteralPath $Temp -Destination $Path -Force
}

function Set-SystemFileAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm('O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Get-NativePowerShellPath {
    $System32 = Join-Path $env:WINDIR 'System32'
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return Join-Path $System32 'WindowsPowerShell\v1.0\powershell.exe'
}

function Assert-PowerShellFile {
    param([string]$Path)
    $Tokens = $null
    $Errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($Path, [ref]$Tokens, [ref]$Errors)
    if ($Errors.Count -gt 0) {
        throw "PowerShell parse error: $($Errors[0].Message)"
    }
}

function Write-MaintenanceStatus {
    param([string]$State, [bool]$Ok, [string]$Message)
    if ($null -eq $Message) {
        $Message = ''
    }
    $Limit = [math]::Min(500, $Message.Length)
    $Payload = [ordered]@{
        state = $State
        action = $Action
        repository_ref = $RepositoryRef.ToLowerInvariant()
        ok = $Ok
        message = $Message.Substring(0, $Limit)
        updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }
    Write-JsonAtomic -Path $StatusPath -Value $Payload
    Set-SystemFileAcl -Path $StatusPath
}

if ($RepositoryRef -notmatch '^[0-9a-fA-F]{40}$') {
    throw 'Maintenance requires an immutable 40-character commit SHA.'
}
$RepositoryRef = $RepositoryRef.ToLowerInvariant()

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw 'device.json отсутствует.'
}
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ([string]$Config.device_id -ne $ExpectedDeviceId) {
    throw 'ExpectedDeviceId не совпадает с локальной identity.'
}

New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
Write-JsonAtomic -Path $ActivePath -Value ([ordered]@{
    action = $Action
    repository_ref = $RepositoryRef
    started_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    pid = $PID
})
Set-SystemFileAcl -Path $ActivePath
Write-MaintenanceStatus -State 'running' -Ok $false -Message 'Maintenance started'

try {
    $ScriptName = if ($Action -eq 'repair') { 'repair-client.ps1' } else { 'update-client.ps1' }
    $Url = "https://raw.githubusercontent.com/$Repo/$RepositoryRef/scripts/$ScriptName"

    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Candidate
    Assert-PowerShellFile -Path $Candidate

    $NativePowerShell = Get-NativePowerShellPath
    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Candidate, '-RepositoryRef', $RepositoryRef)
    if ($Action -eq 'repair') {
        $Args += @('-ExpectedDeviceId', $ExpectedDeviceId)
    }

    $Output = & $NativePowerShell @Args 2>&1 | Out-String
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "$Action failed with code $ExitCode. $($Output.Trim())"
    }

    $RefTemp = "$ClientRefPath.tmp"
    Set-Content -LiteralPath $RefTemp -Value $RepositoryRef -Encoding ASCII
    Move-Item -LiteralPath $RefTemp -Destination $ClientRefPath -Force
    Set-SystemFileAcl -Path $ClientRefPath

    $Summary = if ($Output.Trim()) {
        (($Output.Trim() -split "\r?\n" | Select-Object -Last 8) -join ' | ')
    }
    else {
        "$Action completed"
    }
    Write-MaintenanceStatus -State 'completed' -Ok $true -Message $Summary
    exit 0
}
catch {
    Write-MaintenanceStatus -State 'failed' -Ok $false -Message $_.Exception.Message
    exit 1
}
finally {
    Remove-Item -LiteralPath $Candidate -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ActivePath -Force -ErrorAction SilentlyContinue
}
