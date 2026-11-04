param(
    [switch]$Rollback
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$BaseDir = 'C:\ProgramData\HermesRDP'
$ConfigPath = Join-Path $BaseDir 'device.json'
$BackupPath = Join-Path $BaseDir 'rdp-certificate-backup.json'
$RdpNamespace = 'root/cimv2/TerminalServices'
$RdpFilter = "TerminalName='RDP-tcp'"
$RdpRegPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp'

Write-Host '=== CERT-011 ==='

function Normalize-Thumbprint {
    param([string]$Value)
    return (($Value -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-JsonFile {
    param([string]$Path, [object]$Value)
    $Temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $Temp -Encoding UTF8
    Move-Item -LiteralPath $Temp -Destination $Path -Force
}

function Set-SecretAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
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
        throw 'Некорректный previous RDP certificate thumbprint.'
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
            throw 'Default self-signed RDP thumbprint не восстановился.'
        }
        if (Get-RegistryBindingPresent) {
            throw 'Custom registry binding остался после default rollback.'
        }
        return
    }

    if ($HashType -eq 3) {
        Set-RdpThumbprint -Thumbprint $Clean
        Start-Sleep -Milliseconds 500
        $Check = Get-RdpSetting
        $Actual = Normalize-Thumbprint -Value ([string]$Check.SSLCertificateSHA1Hash)
        if ([int]$Check.SSLCertificateSHA1HashType -ne 3 -or $Actual -ne $Clean) {
            throw 'Previous custom RDP binding не восстановился.'
        }
        return
    }

    throw "Неподдерживаемый previous RDP hash type для rollback: $HashType"
}

function Get-PrivateKeyInfo {
    param([System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate)

    $Rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey(
        $Certificate
    )
    if (-not $Rsa) {
        throw 'У сертификата нет RSA private key.'
    }
    try {
        if ($Rsa -is [System.Security.Cryptography.RSACryptoServiceProvider]) {
            $Info = $Rsa.CspKeyContainerInfo
            return [pscustomobject]@{
                Path = Join-Path `
                    $env:ProgramData `
                    "Microsoft\Crypto\RSA\MachineKeys\$($Info.UniqueKeyContainerName)"
                Exportable = [bool]$Info.Exportable
                Provider = 'CAPI'
            }
        }
        if ($Rsa.GetType().FullName -eq 'System.Security.Cryptography.RSACng') {
            $ExportPolicy = $Rsa.Key.ExportPolicy
            $AllowExport = (
                ($ExportPolicy -band [System.Security.Cryptography.CngExportPolicies]::AllowExport) -ne 0 -or
                ($ExportPolicy -band [System.Security.Cryptography.CngExportPolicies]::AllowPlaintextExport) -ne 0
            )
            return [pscustomobject]@{
                Path = Join-Path `
                    $env:ProgramData `
                    "Microsoft\Crypto\Keys\$($Rsa.Key.UniqueName)"
                Exportable = [bool]$AllowExport
                Provider = 'CNG'
            }
        }
        throw "Неподдерживаемый RSA provider: $($Rsa.GetType().FullName)"
    }
    finally {
        $Rsa.Dispose()
    }
}

function Grant-NetworkServiceRead {
    param([string]$KeyPath)
    if (-not (Test-Path -LiteralPath $KeyPath)) {
        throw "Private key file не найден: $KeyPath"
    }
    $Acl = Get-Acl -LiteralPath $KeyPath
    $Sid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-20')
    $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $Sid,
        [System.Security.AccessControl.FileSystemRights]::Read,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void]$Acl.AddAccessRule($Rule)
    Set-Acl -LiteralPath $KeyPath -AclObject $Acl

    $Verified = Get-Acl -LiteralPath $KeyPath
    $Allowed = @(
        $Verified.Access | Where-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value -eq 'S-1-5-20' -and
            $_.AccessControlType -eq 'Allow' -and
            (($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Read) -ne 0)
        }
    )
    if ($Allowed.Count -eq 0) {
        throw 'Не удалось подтвердить NETWORK SERVICE Read на private key.'
    }
}

$SyncMutex = New-Object System.Threading.Mutex(
    $false,
    'Global\HermesRdpCertificateSync'
)
$SyncMutexHeld = $false
try {
    try {
        $SyncMutexHeld = $SyncMutex.WaitOne(
            [TimeSpan]::FromSeconds(45)
        )
    }
    catch [System.Threading.AbandonedMutexException] {
        $SyncMutexHeld = $true
    }
    if (-not $SyncMutexHeld) {
        throw 'Certificate sync is already running.'
    }

if ($Rollback) {
    $Backup = Read-JsonFile -Path $BackupPath
    if (-not $Backup) {
        throw "Rollback-файл не найден: $BackupPath"
    }
    $OldHash = Normalize-Thumbprint -Value ([string]$Backup.previous_thumbprint)
    $OldType = [int]$Backup.previous_hash_type
    Restore-RdpBinding -Thumbprint $OldHash -HashType $OldType
    $Check = Get-RdpSetting
    $Actual = Normalize-Thumbprint -Value ([string]$Check.SSLCertificateSHA1Hash)
    if ($Actual -ne $OldHash -or [int]$Check.SSLCertificateSHA1HashType -ne $OldType) {
        throw 'Rollback RDP binding не подтвердился.'
    }
    Write-Host 'ROLLBACK=PASS'
    Write-Host "RDP_THUMBPRINT=$Actual"
    Write-Host "RDP_HASH_TYPE=$OldType"
    Write-Host 'CERT-011=ROLLBACK_PASS'
    exit 0
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Hermes device config не найден: $ConfigPath"
}
$Config = Read-JsonFile -Path $ConfigPath
if (-not $Config) {
    throw 'Hermes device config пуст или повреждён.'
}
foreach ($Name in @('device_id','device_token','api_base_url','api_fingerprint')) {
    if ([string]::IsNullOrWhiteSpace([string]$Config.$Name)) {
        throw "В Hermes device config отсутствует $Name."
    }
}

$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentPrincipal = New-Object Security.Principal.WindowsPrincipal($CurrentIdentity)
if (-not $CurrentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Открой PowerShell от имени администратора.'
}

$PinnedHttpClientSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace HermesRdp
{
    public static class CertificatePinnedHttpClientFactory
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
                    return String.Equals(actual, expected, StringComparison.OrdinalIgnoreCase);
                }
            };
            var client = new HttpClient(handler);
            client.Timeout = TimeSpan.FromSeconds(30);
            return client;
        }
    }
}
'@

if (-not ('HermesRdp.CertificatePinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $PinnedHttpClientSource `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
}

$Http = [HermesRdp.CertificatePinnedHttpClientFactory]::Create(
    [string]$Config.api_fingerprint
)
$Request = $null
$Response = $null
$PfxPath = $null
$ImportedNew = $false
$PreviousHash = $null
$PreviousHashType = $null
$NewThumbprint = $null
try {
    $Request = New-Object System.Net.Http.HttpRequestMessage(
        [System.Net.Http.HttpMethod]::Post,
        "$($Config.api_base_url)/v1/devices/$($Config.device_id)/rdp-certificate"
    )
    $Request.Headers.Authorization =
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue(
            'Bearer',
            [string]$Config.device_token
        )
    $Request.Content = New-Object System.Net.Http.StringContent(
        '{}',
        [Text.Encoding]::UTF8,
        'application/json'
    )
    $Response = $Http.SendAsync($Request).GetAwaiter().GetResult()
    $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if (-not $Response.IsSuccessStatusCode) {
        throw "Hermes API HTTP $([int]$Response.StatusCode): $Text"
    }
    $Payload = $Text | ConvertFrom-Json
    if (-not $Payload.ok -or -not $Payload.certificate) {
        throw 'Hermes API вернул некорректный certificate package.'
    }
    $Package = $Payload.certificate
    $NewThumbprint = Normalize-Thumbprint -Value ([string]$Package.thumbprint)
    if ($NewThumbprint.Length -ne 40) {
        throw 'Сервер вернул некорректный certificate thumbprint.'
    }
    if ([string]::IsNullOrWhiteSpace([string]$Package.pfx_base64)) {
        throw 'Сервер вернул пустой PFX.'
    }
    if ([string]::IsNullOrWhiteSpace([string]$Package.password)) {
        throw 'Сервер вернул пустой PFX password.'
    }
    Write-Host 'PACKAGE_AUTH=PASS'

    $RdpBefore = Get-RdpSetting
    $PreviousHash = Normalize-Thumbprint -Value ([string]$RdpBefore.SSLCertificateSHA1Hash)
    $PreviousHashType = [int]$RdpBefore.SSLCertificateSHA1HashType
    if ($PreviousHash.Length -ne 40) {
        throw 'Не удалось получить текущий RDP certificate thumbprint.'
    }
    if ($PreviousHashType -notin @(1, 3)) {
        throw "Hermes не поддерживает transactional rollback из RDP hash type $PreviousHashType."
    }
    $Backup = [ordered]@{
        captured_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        previous_thumbprint = $PreviousHash
        previous_hash_type = $PreviousHashType
        target_thumbprint = $NewThumbprint
    }
    Write-JsonFile -Path $BackupPath -Value $Backup
    Set-SecretAcl -Path $BackupPath

    $TargetCert = Get-ChildItem -LiteralPath 'Cert:\LocalMachine\My' |
        Where-Object {
            (Normalize-Thumbprint -Value $_.Thumbprint) -eq $NewThumbprint
        } |
        Select-Object -First 1

    if (-not $TargetCert) {
        $PfxPath = Join-Path $BaseDir (
            "rdp-cert-$([Guid]::NewGuid().ToString('N')).pfx"
        )
        [IO.File]::WriteAllBytes(
            $PfxPath,
            [Convert]::FromBase64String([string]$Package.pfx_base64)
        )
        Set-SecretAcl -Path $PfxPath
        $Password = ConvertTo-SecureString `
            -String ([string]$Package.password) `
            -AsPlainText `
            -Force
        $TargetCert = Import-PfxCertificate `
            -FilePath $PfxPath `
            -CertStoreLocation 'Cert:\LocalMachine\My' `
            -Password $Password `
            -Confirm:$false
        $TargetCert = @($TargetCert | Where-Object {
            (Normalize-Thumbprint -Value $_.Thumbprint) -eq $NewThumbprint
        }) | Select-Object -First 1
        if (-not $TargetCert) {
            throw 'Импортированный сертификат не найден по ожидаемому thumbprint.'
        }
        $ImportedNew = $true
    }

    if (-not $TargetCert.HasPrivateKey) {
        throw 'Импортированный RDP certificate не содержит private key.'
    }
    if ((Normalize-Thumbprint -Value $TargetCert.Thumbprint) -ne $NewThumbprint) {
        throw 'Локальный certificate thumbprint не совпал с серверным.'
    }
    Write-Host 'PFX_IMPORT=PASS'

    $KeyInfo = Get-PrivateKeyInfo -Certificate $TargetCert
    if ($KeyInfo.Exportable) {
        throw 'Private key оказался exportable; Hermes запрещает такой импорт.'
    }
    Write-Host "PRIVATE_KEY_PROVIDER=$($KeyInfo.Provider)"
    Write-Host 'PRIVATE_KEY_EXPORTABLE=False'

    Grant-NetworkServiceRead -KeyPath $KeyInfo.Path
    Write-Host 'NETWORK_SERVICE_READ=PASS'

    Set-RdpThumbprint -Thumbprint $NewThumbprint
    Start-Sleep -Milliseconds 500
    $RdpAfter = Get-RdpSetting
    $ActualHash = Normalize-Thumbprint -Value ([string]$RdpAfter.SSLCertificateSHA1Hash)
    if ($ActualHash -ne $NewThumbprint) {
        throw 'Новый RDP certificate thumbprint не применился.'
    }
    if ([int]$RdpAfter.SSLCertificateSHA1HashType -ne 3) {
        throw "RDP certificate hash type не стал CUSTOM: $($RdpAfter.SSLCertificateSHA1HashType)"
    }

    $Listener = @(Get-NetTCPConnection `
        -LocalPort 3389 `
        -State Listen `
        -ErrorAction SilentlyContinue)
    if ($Listener.Count -eq 0) {
        throw 'RDP listener 3389 пропал после certificate binding.'
    }

    Write-Host "OLD_RDP_THUMBPRINT=$PreviousHash"
    Write-Host "NEW_RDP_THUMBPRINT=$ActualHash"
    Write-Host 'HASH_TYPE=CUSTOM'
    Write-Host 'RDP_3389=LISTEN'
    Write-Host "ROLLBACK_FILE=$BackupPath"
    Write-Host 'CERT-011=LOCAL_BIND_PASS'
}
catch {
    $Failure = $_
    if ($PreviousHash -and $PreviousHash.Length -eq 40 -and $null -ne $PreviousHashType) {
        try {
            Restore-RdpBinding `
                -Thumbprint $PreviousHash `
                -HashType ([int]$PreviousHashType)
            Write-Host 'AUTO_ROLLBACK=PASS'
        }
        catch {
            Write-Host "AUTO_ROLLBACK=FAIL:$($_.Exception.Message)"
        }
    }
    if ($ImportedNew -and $NewThumbprint) {
        try {
            $Bound = Normalize-Thumbprint -Value ([string](Get-RdpSetting).SSLCertificateSHA1Hash)
            if ($Bound -ne $NewThumbprint) {
                Get-ChildItem -LiteralPath 'Cert:\LocalMachine\My' |
                    Where-Object {
                        (Normalize-Thumbprint -Value $_.Thumbprint) -eq $NewThumbprint
                    } |
                    Remove-Item -Force -ErrorAction SilentlyContinue
            }
        }
        catch {
        }
    }
    throw $Failure
}
finally {
    if ($PfxPath -and (Test-Path -LiteralPath $PfxPath)) {
        Remove-Item -LiteralPath $PfxPath -Force -ErrorAction SilentlyContinue
    }
    if ($Response) {
        $Response.Dispose()
    }
    if ($Request) {
        $Request.Dispose()
    }
    if ($Http) {
        $Http.Dispose()
    }
}
}
finally {
    if ($SyncMutexHeld) {
        try {
            $SyncMutex.ReleaseMutex()
        }
        catch {
        }
    }
    $SyncMutex.Dispose()
}
