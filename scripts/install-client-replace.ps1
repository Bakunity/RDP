param(
    [Parameter(Mandatory = $true)]
    [string]$Server,

    [Parameter(Mandatory = $true)]
    [string]$PairCode,

    [Parameter(Mandatory = $true)]
    [string]$Fingerprint,

    [string]$Name,
    [int]$ApiPort = 7443,
    [string]$RepositoryRef = 'main',
    [switch]$ReplaceExisting
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$AgentTaskName = 'Hermes RDP Agent'
$RotationTaskName = 'Hermes RDP Certificate Rotation'
$ConfigPath = Join-Path $BaseDir 'device.json'
$PrivateKeyPath = Join-Path $BaseDir 'id_ed25519'
$PublicKeyPath = "$PrivateKeyPath.pub"
$CoreCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpInstallCore-$([Guid]::NewGuid().ToString('N')).ps1")

$PinnedHttpClientSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace HermesRdpReplace
{
    public static class PinnedHttpClientFactory
    {
        private static string NormalizeFingerprint(string value)
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

        public static HttpClient Create(string expectedFingerprint)
        {
            string expected = NormalizeFingerprint(expectedFingerprint);
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

if (-not ('HermesRdpReplace.PinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $PinnedHttpClientSource `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
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

function Get-TaskSnapshot {
    param([string]$TaskName)

    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $Task) {
        return [pscustomobject]@{
            Exists = $false
            State = 'ABSENT'
            Xml = $null
        }
    }

    return [pscustomobject]@{
        Exists = $true
        State = [string]$Task.State
        Xml = [string](Export-ScheduledTask -TaskName $TaskName)
    }
}

function Stop-TaskBounded {
    param([string]$TaskName)

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
    throw "Scheduled Task '$TaskName' did not stop within 10 seconds."
}

function Remove-HermesTask {
    param([string]$TaskName)

    Stop-TaskBounded -TaskName $TaskName
    Unregister-ScheduledTask `
        -TaskName $TaskName `
        -Confirm:$false `
        -ErrorAction SilentlyContinue
}

function Restore-TaskSnapshot {
    param(
        [string]$TaskName,
        [object]$Snapshot
    )

    Remove-HermesTask -TaskName $TaskName
    if (-not $Snapshot -or -not [bool]$Snapshot.Exists) {
        return
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Xml ([string]$Snapshot.Xml) `
        -Force |
        Out-Null

    if ([string]$Snapshot.State -eq 'Running') {
        Start-ScheduledTask -TaskName $TaskName
    }
}

function Stop-HermesProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($BaseDir)
        } |
        ForEach-Object {
            Stop-Process `
                -Id $_.ProcessId `
                -Force `
                -ErrorAction SilentlyContinue
        }
}

function Get-ExistingHermesConfig {
    if (
        -not (Test-Path -LiteralPath $ConfigPath) -or
        -not (Test-Path -LiteralPath $PrivateKeyPath) -or
        -not (Test-Path -LiteralPath $PublicKeyPath)
    ) {
        return $null
    }

    try {
        $Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }

    if (
        -not $Config -or
        [string]::IsNullOrWhiteSpace([string]$Config.device_id) -or
        [int]$Config.rdp_port -le 0 -or
        [string]::IsNullOrWhiteSpace([string]$Config.ssh_key_path)
    ) {
        return $null
    }
    return $Config
}

function Get-ConfigApiPort {
    param([object]$Config)

    try {
        $Uri = [Uri]([string]$Config.api_base_url)
        if ($Uri.Port -gt 0) {
            return [int]$Uri.Port
        }
    }
    catch {
    }
    return 7443
}

function Invoke-PinnedRevoke {
    param([object]$Config)

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

    $Client = [HermesRdpReplace.PinnedHttpClientFactory]::Create(
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
        '{"reason":"client-replaced-server"}',
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

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$CoreUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/install-client-core.ps1"
)
try {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CoreUrl `
        -OutFile $CoreCandidate
    Assert-PowerShellFile -Path $CoreCandidate

    $ExistingConfig = Get-ExistingHermesConfig
    $Replacing = $false
    $BackupDir = $null
    $AgentTaskSnapshot = $null
    $RotationTaskSnapshot = $null

    if ($ExistingConfig) {
        $ExistingServer = [string]$ExistingConfig.server
        $ExistingApiPort = Get-ConfigApiPort -Config $ExistingConfig
        $SameServer = (
            -not [string]::IsNullOrWhiteSpace($ExistingServer) -and
            [string]::Equals(
                $ExistingServer,
                $Server,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            $ExistingApiPort -eq $ApiPort
        )

        if ($SameServer) {
            throw (
                "Hermes RDP уже установлен на этом ПК и подключён к этому " +
                "серверу (RDP-порт $($ExistingConfig.rdp_port)). " +
                "Для восстановления или обновления используйте repair/update."
            )
        }

        Write-Host '=== HERMES RDP SERVER REPLACE ===' -ForegroundColor Cyan
        Write-Host 'На этом ПК уже есть Hermes RDP.'
        if (-not [string]::IsNullOrWhiteSpace($ExistingServer)) {
            Write-Host "Текущий сервер: $ExistingServer`:$ExistingApiPort"
        }
        else {
            Write-Host 'Текущий сервер: неизвестен'
        }
        Write-Host "Новый сервер:   $Server`:$ApiPort"
        Write-Host "Текущий RDP-порт: $($ExistingConfig.rdp_port)"
        Write-Host
        Write-Host (
            'Старая локальная identity будет сохранена до успешного запуска ' +
            'нового туннеля. После успеха старые credentials будут отозваны.'
        )

        if (-not $ReplaceExisting) {
            $Answer = Read-Host 'Введите REPLACE для переподключения к новому серверу'
            if ($Answer -ne 'REPLACE') {
                throw 'Переподключение отменено. Текущий Hermes RDP не изменён.'
            }
        }

        $Replacing = $true
        $AgentTaskSnapshot = Get-TaskSnapshot -TaskName $AgentTaskName
        $RotationTaskSnapshot = Get-TaskSnapshot -TaskName $RotationTaskName

        Stop-TaskBounded -TaskName $AgentTaskName
        Stop-TaskBounded -TaskName $RotationTaskName
        Stop-HermesProcesses

        $BackupDir = "$BaseDir.replace.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        if (Test-Path -LiteralPath $BackupDir) {
            $BackupDir += ".$([Guid]::NewGuid().ToString('N'))"
        }

        Move-Item -LiteralPath $BaseDir -Destination $BackupDir
        Remove-HermesTask -TaskName $AgentTaskName
        Remove-HermesTask -TaskName $RotationTaskName
    }

    $CoreParams = @{
        Server = $Server
        PairCode = $PairCode
        Fingerprint = $Fingerprint
        ApiPort = $ApiPort
        RepositoryRef = $ResolvedSha
    }
    if ($PSBoundParameters.ContainsKey('Name')) {
        $CoreParams.Name = $Name
    }

    try {
        & $CoreCandidate @CoreParams

        if ($Replacing) {
            $OldRevoke = Invoke-PinnedRevoke -Config $ExistingConfig
            if ($OldRevoke -eq 'REVOKED') {
                Write-Host 'Старая регистрация Hermes отозвана.'
            }
            elseif ($OldRevoke -eq 'UNAVAILABLE') {
                Write-Warning (
                    'В старой конфигурации недостаточно данных для автоматического ' +
                    'отзыва. Удали старое устройство в Telegram старого сервера.'
                )
            }
            else {
                Write-Warning (
                    'Старый сервер недоступен или не принял revoke. Новый Hermes ' +
                    'уже работает; удали старую запись устройства в Telegram ' +
                    'старого сервера.'
                )
            }

            if ($BackupDir -and (Test-Path -LiteralPath $BackupDir)) {
                Remove-Item `
                    -LiteralPath $BackupDir `
                    -Recurse `
                    -Force `
                    -ErrorAction SilentlyContinue
            }

            Write-Host
            Write-Host 'REPLACE=PASS' -ForegroundColor Green
            Write-Host "OLD_REGISTRATION=$OldRevoke"
        }
    }
    catch {
        $Failure = $_

        if ($Replacing -and $BackupDir -and (Test-Path -LiteralPath $BackupDir)) {
            try {
                Remove-HermesTask -TaskName $AgentTaskName
                Remove-HermesTask -TaskName $RotationTaskName
                Stop-HermesProcesses

                if (Test-Path -LiteralPath $BaseDir) {
                    Remove-Item `
                        -LiteralPath $BaseDir `
                        -Recurse `
                        -Force `
                        -ErrorAction Stop
                }

                Move-Item -LiteralPath $BackupDir -Destination $BaseDir
                Restore-TaskSnapshot `
                    -TaskName $AgentTaskName `
                    -Snapshot $AgentTaskSnapshot
                Restore-TaskSnapshot `
                    -TaskName $RotationTaskName `
                    -Snapshot $RotationTaskSnapshot

                Write-Host 'REPLACE_ROLLBACK=PASS' -ForegroundColor Yellow
                Write-Warning (
                    'Старое подключение восстановлено. Если новый сервер успел ' +
                    'принять pairing, в его Telegram может остаться неактивная ' +
                    'запись устройства — её можно удалить.'
                )
            }
            catch {
                Write-Warning (
                    'Автоматический rollback переподключения не завершился. ' +
                    "Резервная копия: $BackupDir"
                )
            }
        }

        throw $Failure
    }
}
finally {
    Remove-Item `
        -LiteralPath $CoreCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
