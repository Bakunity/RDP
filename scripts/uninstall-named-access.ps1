param(
    [switch]$Force
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$BaseDir = 'C:\ProgramData\BakunityRDP\NamedAccess'
$StatePath = Join-Path $BaseDir 'state.json'
$TaskName = 'Bakunity RDP Named Access'
$ShortcutPath = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Bakunity RDP.lnk'
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$HostsBegin = '# BEGIN BAKUNITY RDP NAMED ACCESS'
$HostsEnd = '# END BAKUNITY RDP NAMED ACCESS'
$ListenPort = 3389

if (-not $Force) {
    $Answer = Read-Host 'Введите REMOVE для удаления Bakunity Named Access'
    if ($Answer -ne 'REMOVE') {
        throw 'Удаление отменено.'
    }
}

function Get-NativeSystem32 {
    $System32 = Join-Path $env:WINDIR 'System32'
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return $System32
}

$NativeSystem32 = Get-NativeSystem32
$Netsh = Join-Path $NativeSystem32 'netsh.exe'
$Ipconfig = Join-Path $NativeSystem32 'ipconfig.exe'

function Stop-TaskBounded {
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $Task) {
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
    throw 'Named Access task did not stop within 10 seconds.'
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

$ConnectorId = ''
$State = $null
if (Test-Path -LiteralPath $StatePath) {
    try {
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $ConnectorId = [string]$State.connector_id
    }
    catch {
        $State = $null
    }
}

Stop-TaskBounded
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

if ($State -and $State.mappings) {
    foreach ($Property in $State.mappings.PSObject.Properties) {
        $Address = [string]$Property.Value.loopback
        if ($Address -match '^127\.77\.\d{1,3}\.\d{1,3}$') {
            & $Netsh interface portproxy delete v4tov4 `
                listenaddress=$Address `
                listenport=$ListenPort `
                protocol=tcp *> $null
        }
    }
}

if (Test-Path -LiteralPath $HostsPath) {
    $Original = [IO.File]::ReadAllText($HostsPath)
    $Clean = Remove-ManagedHostsBlock -Text $Original
    if ($Clean -ne $Original) {
        [IO.File]::WriteAllText(
            $HostsPath,
            $Clean.TrimEnd("`r", "`n") + [Environment]::NewLine,
            (New-Object Text.UTF8Encoding($false))
        )
        & $Ipconfig /flushdns | Out-Null
    }
}

Remove-Item -LiteralPath $ShortcutPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BaseDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host 'NAMED_ACCESS_UNINSTALL=PASS' -ForegroundColor Green
if ($ConnectorId) {
    Write-Host "CONNECTOR_ID=$ConnectorId"
    Write-Host 'Server token remains valid until revoked with bakunity-rdpctl named-access revoke CONNECTOR_ID.'
}
