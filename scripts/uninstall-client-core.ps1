param([switch]$Force)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$BaseDir = 'C:\ProgramData\HermesRDP'
$TaskName = 'Hermes RDP Agent'
$RotationTaskName = 'Hermes RDP Certificate Rotation'
$AgentPath = Join-Path $BaseDir 'HermesRdpAgent.ps1'
$RotationPath = Join-Path $BaseDir 'HermesRdpCertRotation.ps1'
$SyncPath = Join-Path $BaseDir 'sync-rdp-certificate.ps1'
$ConfigPath = Join-Path $BaseDir 'device.json'
$OriginPath = Join-Path $BaseDir 'rdp-certificate-origin.json'
$LegacyBackupPath = Join-Path $BaseDir 'rdp-certificate-backup.json'
$RdpNamespace = 'root/cimv2/TerminalServices'
$RdpFilter = "TerminalName='RDP-tcp'"
$RdpRegPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp'

Write-Host '=== HERMES RDP UNINSTALL ===' -ForegroundColor Cyan

if (-not $Force) {
    $Answer = Read-Host 'Введите REMOVE для полного удаления Hermes RDP с этого ПК'
    if ($Answer -ne 'REMOVE') {
        throw 'Удаление отменено. Hermes RDP не изменён.'
    }
}

function Normalize-Thumbprint {
    param([string]$Value)
    return (($Value -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
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

function Get-RdpSetting {
    return Get-CimInstance `
        -Namespace $RdpNamespace `
        -ClassName Win32_TSGeneralSetting `
        -Filter $RdpFilter
}

function Get-RegistryBindingPresent {
    $Item = Get-Item -LiteralPath $RdpRegPath
    return ($Item.Property -contains 'SSLCertificateSHA1Hash')
}

function Set-RdpThumbprint {
    param([string]$Thumbprint)
    $Clean = Normalize-Thumbprint -Value $Thumbprint
    if ($Clean.Length -ne 40) {
        throw 'Некорректный RDP certificate thumbprint.'
    }
    $Setting = Get-RdpSetting
    [void]($Setting | Set-CimInstance -Property @{
        SSLCertificateSHA1Hash = $Clean
    })
}

function Restore-RdpBinding {
    param(
        [string]$Thumbprint,
        [int]$HashType
    )

    $Clean = Normalize-Thumbprint -Value $Thumbprint
    if ($Clean.Length -ne 40) {
        throw 'Некорректный сохранённый RDP thumbprint.'
    }

    if ($HashType -eq 1) {
        if (Get-RegistryBindingPresent) {
            Remove-ItemProperty `
                -LiteralPath $RdpRegPath `
                -Name SSLCertificateSHA1Hash `
                -Force
        }
        Start-Sleep -Milliseconds 500
        $Check = Get-RdpSetting
        $Actual = Normalize-Thumbprint -Value ([string]$Check.SSLCertificateSHA1Hash)
        if ([int]$Check.SSLCertificateSHA1HashType -ne 1) {
            throw "Default self-signed hash type не восстановился: $($Check.SSLCertificateSHA1HashType)"
        }
        if ($Actual -ne $Clean) {
            throw 'Исходный self-signed RDP thumbprint не восстановился.'
        }
        if (Get-RegistryBindingPresent) {
            throw 'Custom registry binding остался после восстановления default RDP state.'
        }
        return $Actual
    }

    if ($HashType -eq 3) {
        Set-RdpThumbprint -Thumbprint $Clean
        Start-Sleep -Milliseconds 500
        $Check = Get-RdpSetting
        $Actual = Normalize-Thumbprint -Value ([string]$Check.SSLCertificateSHA1Hash)
        if ([int]$Check.SSLCertificateSHA1HashType -ne 3 -or $Actual -ne $Clean) {
            throw 'Исходный custom RDP certificate binding не восстановился.'
        }
        return $Actual
    }

    throw "Неподдерживаемый сохранённый RDP hash type: $HashType"
}

function Get-RdpOriginSnapshot {
    $Origin = Read-JsonFile -Path $OriginPath
    if ($Origin) {
        $Thumbprint = Normalize-Thumbprint -Value ([string]$Origin.original_thumbprint)
        $HashType = [int]$Origin.original_hash_type
        if ($Thumbprint.Length -eq 40 -and $HashType -in @(1, 3)) {
            return [pscustomobject]@{
                Thumbprint = $Thumbprint
                HashType = $HashType
                Source = 'ORIGIN'
            }
        }
        throw 'RDP origin snapshot повреждён; удаление остановлено до отзыва credentials.'
    }

    $Legacy = Read-JsonFile -Path $LegacyBackupPath
    if ($Legacy) {
        $Thumbprint = Normalize-Thumbprint -Value ([string]$Legacy.previous_thumbprint)
        $HashType = [int]$Legacy.previous_hash_type
        if ($Thumbprint.Length -eq 40 -and $HashType -in @(1, 3)) {
            return [pscustomobject]@{
                Thumbprint = $Thumbprint
                HashType = $HashType
                Source = 'LEGACY_BACKUP'
            }
        }
    }

    return $null
}

function Stop-TaskBounded {
    param([string]$Name)
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $Task) {
        return
    }
    Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        $Current = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if (-not $Current -or [string]$Current.State -ne 'Running') {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Scheduled Task '$Name' did not stop within 10 seconds."
}

function Stop-HermesProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq 'frpc.exe') -or
            ($_.Name -eq 'ssh.exe' -and $_.CommandLine -and
                $_.CommandLine.Contains('HermesRDP')) -or
            ($_.CommandLine -and
                $_.CommandLine.Contains($AgentPath)) -or
            ($_.CommandLine -and
                $_.CommandLine.Contains($RotationPath)) -or
            ($_.CommandLine -and
                $_.CommandLine.Contains($SyncPath))
        } |
        ForEach-Object {
            Stop-Process `
                -Id ([int]$_.ProcessId) `
                -Force `
                -ErrorAction SilentlyContinue
        }
}

$PinnedHttpClientSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace HermesRdpUninstall
{
    public static class PinnedHttpClientFactory
    {
        private static string Normalize(string value)
        {
            var result = new StringBuilder();
            if (value == null) return String.Empty;
            foreach (char character in value)
            {
                if (Uri.IsHexDigit(character))
                    result.Append(Char.ToUpperInvariant(character));
            }
            return result.ToString();
        }

        public static HttpClient Create(string fingerprint)
        {
            string expected = Normalize(fingerprint);
            var handler = new HttpClientHandler();
            handler.ServerCertificateCustomValidationCallback = delegate(
                HttpRequestMessage request,
                X509Certificate2 certificate,
                X509Chain chain,
                SslPolicyErrors errors)
            {
                if (certificate == null || expected.Length != 64) return false;
                using (SHA256 sha = SHA256.Create())
                {
                    string actual = BitConverter.ToString(
                        sha.ComputeHash(certificate.RawData)
                    ).Replace("-", String.Empty);
                    return String.Equals(
                        actual,
                        expected,
                        StringComparison.OrdinalIgnoreCase
                    );
                }
            };
            var client = new HttpClient(handler);
            client.Timeout = TimeSpan.FromSeconds(20);
            return client;
        }
    }
}
'@

if (-not ('HermesRdpUninstall.PinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $PinnedHttpClientSource `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
}

function Invoke-PinnedRevoke {
    param([object]$Config)

    if (-not $Config) {
        return 'UNAVAILABLE'
    }
    foreach ($Property in @(
        'device_id',
        'device_token',
        'api_base_url',
        'api_fingerprint'
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$Config.$Property)) {
            return 'UNAVAILABLE'
        }
    }

    $Client = [HermesRdpUninstall.PinnedHttpClientFactory]::Create(
        [string]$Config.api_fingerprint
    )
    $Request = New-Object System.Net.Http.HttpRequestMessage(
        [System.Net.Http.HttpMethod]::Post,
        (
            "$($Config.api_base_url)/v1/devices/" +
            "$($Config.device_id)/revoke-self"
        )
    )
    $Request.Content = New-Object System.Net.Http.StringContent(
        '{"reason":"client-uninstall"}',
        [Text.Encoding]::UTF8,
        'application/json'
    )
    $Request.Headers.Authorization =
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue(
            'Bearer',
            [string]$Config.device_token
        )

    try {
        $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        try {
            if (-not $Response.IsSuccessStatusCode) {
                return "FAILED_HTTP_$([int]$Response.StatusCode)"
            }
            return 'REVOKED'
        }
        finally {
            $Response.Dispose()
        }
    }
    catch {
        return 'FAILED'
    }
    finally {
        $Request.Dispose()
        $Client.Dispose()
    }
}

$Config = Read-JsonFile -Path $ConfigPath
$RotationBefore = Get-ScheduledTask `
    -TaskName $RotationTaskName `
    -ErrorAction SilentlyContinue
$RotationWasRunning = (
    $RotationBefore -and [string]$RotationBefore.State -eq 'Running'
)
$CertificateManaged = (
    $null -ne $RotationBefore -or
    (Test-Path -LiteralPath $RotationPath) -or
    (Test-Path -LiteralPath $SyncPath) -or
    (Test-Path -LiteralPath $OriginPath) -or
    (Test-Path -LiteralPath $LegacyBackupPath)
)

$RdpBefore = Get-RdpSetting
$HermesThumbprint = Normalize-Thumbprint -Value ([string]$RdpBefore.SSLCertificateSHA1Hash)
$HermesHashType = [int]$RdpBefore.SSLCertificateSHA1HashType
$RollbackSnapshot = Get-RdpOriginSnapshot
$RestoredThumbprint = $HermesThumbprint
$CertificateRollback = 'NOT_NEEDED'

try {
    Stop-TaskBounded -Name $RotationTaskName

    if ($RollbackSnapshot) {
        $RestoredThumbprint = Restore-RdpBinding `
            -Thumbprint ([string]$RollbackSnapshot.Thumbprint) `
            -HashType ([int]$RollbackSnapshot.HashType)
        $CertificateRollback = "PASS_$($RollbackSnapshot.Source)"

        if (
            $HermesHashType -eq 3 -and
            $HermesThumbprint.Length -eq 40 -and
            $HermesThumbprint -ne $RestoredThumbprint
        ) {
            Get-ChildItem -LiteralPath 'Cert:\LocalMachine\My' |
                Where-Object {
                    (Normalize-Thumbprint -Value ([string]$_.Thumbprint)) -eq $HermesThumbprint
                } |
                Remove-Item -Force -ErrorAction Stop
        }
    }
    elseif ($CertificateManaged -and $HermesHashType -eq 3) {
        throw (
            'Hermes trusted RDP certificate активен, но rollback snapshot не найден. ' +
            'Удаление остановлено до отзыва credentials.'
        )
    }
}
catch {
    if ($RotationWasRunning) {
        Start-ScheduledTask `
            -TaskName $RotationTaskName `
            -ErrorAction SilentlyContinue
    }
    throw
}

Write-Host "CERT_ROLLBACK=$CertificateRollback"

foreach ($HermesTask in @($TaskName, $RotationTaskName)) {
    Stop-TaskBounded -Name $HermesTask
    Unregister-ScheduledTask `
        -TaskName $HermesTask `
        -Confirm:$false `
        -ErrorAction SilentlyContinue
}
Stop-HermesProcesses

$ServerRevoke = Invoke-PinnedRevoke -Config $Config
Write-Host "SERVER_REVOKE=$ServerRevoke"
if ($ServerRevoke -ne 'REVOKED') {
    Write-Warning (
        'Сервер не подтвердил отзыв устройства. Локальные credentials будут ' +
        'удалены, но старую запись при необходимости удали в Telegram.'
    )
}

if (Test-Path -LiteralPath $BaseDir) {
    Remove-Item `
        -LiteralPath $BaseDir `
        -Recurse `
        -Force `
        -ErrorAction Stop
}

$TasksRemaining = @(
    foreach ($HermesTask in @($TaskName, $RotationTaskName)) {
        if (Get-ScheduledTask -TaskName $HermesTask -ErrorAction SilentlyContinue) {
            $HermesTask
        }
    }
)
$ProcessesRemaining = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq 'ssh.exe' -and $_.CommandLine -and
                $_.CommandLine.Contains('HermesRDP')) -or
            ($_.CommandLine -and $_.CommandLine.Contains('HermesRdpAgent.ps1')) -or
            ($_.CommandLine -and $_.CommandLine.Contains('HermesRdpCertRotation.ps1'))
        }
)
$RdpListener = @(
    Get-NetTCPConnection `
        -LocalPort 3389 `
        -State Listen `
        -ErrorAction SilentlyContinue
)

if ($TasksRemaining.Count -ne 0) {
    throw "После удаления остались Hermes Scheduled Tasks: $($TasksRemaining -join ', ')"
}
if ($ProcessesRemaining.Count -ne 0) {
    throw "После удаления остались Hermes процессы: $($ProcessesRemaining.Count)"
}
if (Test-Path -LiteralPath $BaseDir) {
    throw "После удаления остался активный каталог: $BaseDir"
}
if ($RdpListener.Count -eq 0) {
    throw 'RDP listener 3389 отсутствует после удаления Hermes.'
}

Write-Host 'LOCAL_TASKS=ABSENT'
Write-Host 'HERMES_PROCESSES=0'
Write-Host 'LOCAL_STATE=REMOVED'
Write-Host 'RDP_3389=LISTEN'
Write-Host 'UNINSTALL=PASS' -ForegroundColor Green
