param(
    [string]$Computer,
    [switch]$List
)

$ErrorActionPreference = 'Stop'
$BaseDir = 'C:\ProgramData\BakunityRDP\SmartRoute'
$StatePath = Join-Path $BaseDir 'state.json'
$Mstsc = Join-Path $env:WINDIR 'System32\mstsc.exe'

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        throw 'Bakunity Smart Route state is unavailable.'
    }
    return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
}

function Get-Rows {
    param([object]$State)
    $Rows = @()
    if (-not $State.mappings) { return $Rows }
    foreach ($Property in $State.mappings.PSObject.Properties) {
        $Entry = $Property.Value
        $Rows += [pscustomobject]@{
            device_id=[string]$Property.Name
            hostname=[string]$Entry.hostname
            local_port=[int]$Entry.local_port
            enabled=[bool]$Entry.enabled
            route=[string]$Entry.route_type
            latency_ms=[int]$Entry.latency_ms
        }
    }
    return @($Rows | Sort-Object hostname)
}

function Resolve-Target {
    param([array]$Rows, [string]$Value, [string]$Domain)
    $InputValue = ([string]$Value).Trim().ToLowerInvariant()
    if (-not $InputValue) { throw 'Computer name is required.' }
    if ($InputValue.Contains(':')) { throw 'Do not include an RDP port.' }
    $Candidates = @(
        $Rows | Where-Object {
            $HostName = ([string]$_.hostname).ToLowerInvariant()
            $Slug = if ($Domain -and $HostName.EndsWith(".$Domain")) {
                $HostName.Substring(0, $HostName.Length - $Domain.Length - 1)
            } else { '' }
            $HostName -eq $InputValue -or $Slug -eq $InputValue
        }
    )
    if ($Candidates.Count -eq 0) { throw "Bakunity device not found: $InputValue" }
    if ($Candidates.Count -gt 1) { throw "Bakunity device name is ambiguous: $InputValue" }
    return $Candidates[0]
}

$State = Read-State
$Rows = @(Get-Rows -State $State)
if ($List) {
    $Rows | Select-Object hostname,enabled,route,latency_ms | Format-Table -AutoSize
    exit 0
}
if (-not $Computer) {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $Examples = @($Rows | Select-Object -First 8 | ForEach-Object { [string]$_.hostname }) -join [Environment]::NewLine
    $Prompt = 'Введите имя компьютера Bakunity'
    if ($Examples) {
        $Prompt += [Environment]::NewLine + [Environment]::NewLine + 'Доступные адреса:' + [Environment]::NewLine + $Examples
    }
    $Computer = [Microsoft.VisualBasic.Interaction]::InputBox($Prompt, 'Bakunity RDP Smart Route', '')
    if ([string]::IsNullOrWhiteSpace($Computer)) { exit 0 }
}
$Target = Resolve-Target -Rows $Rows -Value $Computer -Domain ([string]$State.device_domain)
if (-not $Target.enabled) { throw "Bakunity RDP access is disabled for $($Target.hostname)." }
if ([string]$Target.route -eq 'unavailable') { throw "No route is available for $($Target.hostname)." }
if (-not (Test-Path -LiteralPath $Mstsc)) { throw "Microsoft Remote Desktop not found: $Mstsc" }
$Endpoint = "$($Target.hostname):$([int]$Target.local_port)"
Write-Host "CONNECTING=$($Target.hostname)"
Write-Host "ROUTE=$($Target.route)"
Write-Host "LATENCY_MS=$([int]$Target.latency_ms)"
Start-Process -FilePath $Mstsc -ArgumentList @("/v:$Endpoint")
