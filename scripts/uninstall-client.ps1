param(
    [switch]$Force,
    [string]$RepositoryRef = 'main'
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$ConfigPath = Join-Path $BaseDir 'device.json'
$CoreCandidate = Join-Path ([IO.Path]::GetTempPath()) (
    "HermesRdpUninstallCore-$([Guid]::NewGuid().ToString('N')).ps1"
)

Write-Host '=== HERMES RDP UNINSTALL ===' -ForegroundColor Cyan

if (-not $Force) {
    $Answer = Read-Host 'Введите REMOVE для полного удаления Hermes RDP с этого ПК'
    if ($Answer -ne 'REMOVE') {
        throw 'Удаление отменено. Hermes RDP не изменён.'
    }
}

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

$PinnedHttpClientSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace HermesRdpUninstallVerify
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
            client.Timeout = TimeSpan.FromSeconds(15);
            return client;
        }
    }
}
'@

if (-not ('HermesRdpUninstallVerify.PinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $PinnedHttpClientSource `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
}

function Invoke-RevokeVerification {
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

    $Client = [HermesRdpUninstallVerify.PinnedHttpClientFactory]::Create(
        [string]$Config.api_fingerprint
    )
    try {
        for ($Attempt = 1; $Attempt -le 2; $Attempt++) {
            $Request = New-Object System.Net.Http.HttpRequestMessage(
                [System.Net.Http.HttpMethod]::Post,
                (
                    "$($Config.api_base_url)/v1/devices/" +
                    "$($Config.device_id)/revoke-self"
                )
            )
            $Request.Content = New-Object System.Net.Http.StringContent(
                '{"reason":"client-uninstall-verify"}',
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
                    $StatusCode = [int]$Response.StatusCode
                    if ($Response.IsSuccessStatusCode) {
                        return 'REVOKED'
                    }
                    if ($StatusCode -in @(401, 403, 404, 410)) {
                        return 'REVOKED_CONFIRMED'
                    }
                    if ($StatusCode -ge 500 -and $Attempt -lt 2) {
                        Start-Sleep -Milliseconds 750
                        continue
                    }
                    return "UNCONFIRMED_HTTP_$StatusCode"
                }
                finally {
                    $Response.Dispose()
                }
            }
            catch {
                if ($Attempt -lt 2) {
                    Start-Sleep -Milliseconds 750
                    continue
                }
                return 'UNCONFIRMED'
            }
            finally {
                $Request.Dispose()
            }
        }
    }
    finally {
        $Client.Dispose()
    }

    return 'UNCONFIRMED'
}

$ConfigBefore = Read-JsonFile -Path $ConfigPath
$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$CoreUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/uninstall-client-core.ps1"
)

try {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CoreUrl `
        -OutFile $CoreCandidate
    Assert-PowerShellFile -Path $CoreCandidate

    $CoreOutput = @()
    $CoreFailure = $null
    try {
        $CoreOutput = @(& $CoreCandidate -Force *>&1)
    }
    catch {
        $CoreFailure = $_
    }

    $CoreLines = @($CoreOutput | ForEach-Object { [string]$_ })
    if ($CoreFailure) {
        foreach ($Line in $CoreLines) {
            if ($Line) {
                Write-Host $Line
            }
        }
        throw $CoreFailure
    }

    $CoreRevokeLine = @(
        $CoreLines | Where-Object { $_ -like 'SERVER_REVOKE=*' }
    ) | Select-Object -Last 1
    $CoreRevoke = if ($CoreRevokeLine) {
        $CoreRevokeLine.Substring('SERVER_REVOKE='.Length)
    }
    else {
        'UNCONFIRMED'
    }

    $ServerRevoke = $CoreRevoke
    if ($CoreRevoke -ne 'REVOKED') {
        $ServerRevoke = Invoke-RevokeVerification -Config $ConfigBefore
    }

    foreach ($Prefix in @('CERT_ROLLBACK=')) {
        $Line = @($CoreLines | Where-Object { $_ -like "$Prefix*" }) |
            Select-Object -Last 1
        if ($Line) {
            Write-Host $Line
        }
    }

    Write-Host "SERVER_REVOKE=$ServerRevoke"
    if ($ServerRevoke -notin @('REVOKED', 'REVOKED_CONFIRMED')) {
        Write-Warning (
            'Серверный отзыв устройства не удалось подтвердить. ' +
            'Локальное удаление завершено; проверь старую запись в Telegram.'
        )
    }

    foreach ($Prefix in @(
        'LOCAL_TASKS=',
        'HERMES_PROCESSES=',
        'LOCAL_STATE=',
        'RDP_3389=',
        'UNINSTALL='
    )) {
        $Line = @($CoreLines | Where-Object { $_ -like "$Prefix*" }) |
            Select-Object -Last 1
        if ($Line) {
            if ($Line -eq 'UNINSTALL=PASS') {
                Write-Host $Line -ForegroundColor Green
            }
            else {
                Write-Host $Line
            }
        }
    }
}
finally {
    Remove-Item `
        -LiteralPath $CoreCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
