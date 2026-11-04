param(
    [string]$Computer,
    [switch]$List
)

$ErrorActionPreference = 'Stop'

$BaseDir = 'C:\ProgramData\BakunityRDP\NamedAccess'
$StatePath = Join-Path $BaseDir 'state.json'
$Mstsc = Join-Path $env:WINDIR 'System32\mstsc.exe'

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        throw (
            'Bakunity Named Access state is unavailable. ' +
            'Run the installer or wait for the Named Access task to sync.'
        )
    }
    try {
        return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    }
    catch {
        throw 'Bakunity Named Access state is unreadable.'
    }
}

function Get-DeviceRows {
    param([object]$State)

    $Rows = @()
    if (-not $State.mappings) {
        return $Rows
    }
    foreach ($Property in $State.mappings.PSObject.Properties) {
        $Entry = $Property.Value
        $Rows += [pscustomobject]@{
            device_id = [string]$Property.Name
            hostname = [string]$Entry.hostname
            rdp_port = [int]$Entry.rdp_port
            enabled = [bool]$Entry.enabled
        }
    }
    return @($Rows | Sort-Object hostname)
}

function Resolve-Target {
    param(
        [array]$Rows,
        [string]$Value,
        [string]$Domain
    )

    $InputValue = ([string]$Value).Trim().ToLowerInvariant()
    if (-not $InputValue) {
        throw 'Computer name is required.'
    }
    if ($InputValue.Contains(':')) {
        throw 'Do not include an RDP port. Use only the Bakunity device name.'
    }
    if ($InputValue -notmatch '^[a-z0-9.-]+$') {
        throw 'Computer name contains unsupported characters.'
    }

    $Candidates = @(
        $Rows | Where-Object {
            $HostName = ([string]$_.hostname).ToLowerInvariant()
            $Slug = if ($Domain -and $HostName.EndsWith(".$Domain")) {
                $HostName.Substring(
                    0,
                    $HostName.Length - $Domain.Length - 1
                )
            }
            else {
                ''
            }
            $HostName -eq $InputValue -or $Slug -eq $InputValue
        }
    )

    if ($Candidates.Count -eq 0) {
        throw "Bakunity device not found: $InputValue"
    }
    if ($Candidates.Count -gt 1) {
        throw "Bakunity device name is ambiguous: $InputValue"
    }
    return $Candidates[0]
}

$State = Read-State
$Rows = @(Get-DeviceRows -State $State)

if ($List) {
    $Rows |
        Select-Object hostname,enabled |
        Format-Table -AutoSize
    exit 0
}

if (-not $Computer) {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $Examples = @(
        $Rows |
            Select-Object -First 6 |
            ForEach-Object { [string]$_.hostname }
    ) -join [Environment]::NewLine
    $Prompt = 'Введите имя компьютера Bakunity'
    if ($Examples) {
        $Prompt += (
            [Environment]::NewLine +
            [Environment]::NewLine +
            'Доступные адреса:' +
            [Environment]::NewLine +
            $Examples
        )
    }
    $Computer = [Microsoft.VisualBasic.Interaction]::InputBox(
        $Prompt,
        'Bakunity RDP',
        ''
    )
    if ([string]::IsNullOrWhiteSpace($Computer)) {
        exit 0
    }
}

$Domain = ([string]$State.device_domain).Trim().ToLowerInvariant()
$Target = Resolve-Target -Rows $Rows -Value $Computer -Domain $Domain

if (-not [bool]$Target.enabled) {
    throw "Bakunity RDP access is disabled for $($Target.hostname)."
}
if (
    [int]$Target.rdp_port -lt 1 -or
    [int]$Target.rdp_port -gt 65535
) {
    throw 'Bakunity RDP target port is invalid.'
}
if (-not (Test-Path -LiteralPath $Mstsc)) {
    throw "Microsoft Remote Desktop client not found: $Mstsc"
}

$Endpoint = "$($Target.hostname):$([int]$Target.rdp_port)"
Write-Host "CONNECTING=$($Target.hostname)"
Start-Process -FilePath $Mstsc -ArgumentList @("/v:$Endpoint")
