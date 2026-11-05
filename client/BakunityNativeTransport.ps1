$script:BakunityNativeTransportRoot = 'C:\ProgramData\BakunityRDP\Transport'
$script:BakunityNativeTransportExe = Join-Path $script:BakunityNativeTransportRoot 'BakunityTransport.exe'
$script:BakunityNativeTransportConfig = Join-Path $script:BakunityNativeTransportRoot 'config.json'
$script:BakunityNativeTransportRef = Join-Path $script:BakunityNativeTransportRoot 'build-ref.txt'
$script:BakunityNativeTransportTask = 'Bakunity Transport'
$script:BakunityNativeTransportControl = 'http://127.0.0.1:48389'

Add-Type -AssemblyName System.Net.Http
$BakunityNativeDownloadSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace BakunityNativeTransportDownload
{
    public static class PinnedHttpClientFactory
    {
        private static string Normalize(string value)
        {
            var result = new StringBuilder();
            if (value == null) return String.Empty;
            foreach (char c in value) {
                if (Uri.IsHexDigit(c)) result.Append(Char.ToUpperInvariant(c));
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
                using (SHA256 sha = SHA256.Create()) {
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
            client.Timeout = TimeSpan.FromSeconds(120);
            return client;
        }
    }
}
'@

if (-not ('BakunityNativeTransportDownload.PinnedHttpClientFactory' -as [type])) {
    Add-Type -TypeDefinition $BakunityNativeDownloadSource -Language CSharp -ReferencedAssemblies 'System.Net.Http.dll'
}

function Set-BakunityNativeSecretAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'D:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Set-BakunityNativeExecutableAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;BU)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Get-BakunityNativePowerShell {
    $System32 = Join-Path $env:WINDIR 'System32'
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return Join-Path $System32 'WindowsPowerShell\v1.0\powershell.exe'
}

function Get-BakunityNativeTransportStatus {
    try {
        return Invoke-RestMethod -UseBasicParsing -Method Get -Uri (
            $script:BakunityNativeTransportControl + '/status'
        ) -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Stop-BakunityNativeTransportTask {
    $Task = Get-ScheduledTask -TaskName $script:BakunityNativeTransportTask -ErrorAction SilentlyContinue
    if (-not $Task) { return }
    Stop-ScheduledTask -TaskName $script:BakunityNativeTransportTask -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 40; $i++) {
        $Current = Get-ScheduledTask -TaskName $script:BakunityNativeTransportTask -ErrorAction SilentlyContinue
        if (-not $Current -or [string]$Current.State -ne 'Running') {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'Bakunity Transport task did not stop.'
}

function Save-BakunityNativeTransportArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$DownloadUrl,
        [Parameter(Mandatory = $true)][string]$ApiFingerprint,
        [Parameter(Mandatory = $true)][string]$BearerToken,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )

    $Client = [BakunityNativeTransportDownload.PinnedHttpClientFactory]::Create($ApiFingerprint)
    $Request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $DownloadUrl)
    $Request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $BearerToken)
    try {
        $Response = $Client.SendAsync($Request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        try {
            if (-not $Response.IsSuccessStatusCode) {
                $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                throw "Bakunity Transport artifact HTTP $([int]$Response.StatusCode): $Text"
            }
            $Input = $Response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            try {
                $Output = New-Object IO.FileStream($OutputPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try {
                    $Input.CopyTo($Output)
                }
                finally {
                    $Output.Dispose()
                }
            }
            finally {
                $Input.Dispose()
            }
        }
        finally {
            $Response.Dispose()
        }
    }
    finally {
        $Request.Dispose()
        $Client.Dispose()
    }
}

function Install-BakunityNativeTransportBinary {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRef,
        [Parameter(Mandatory = $true)][string]$DownloadUrl,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$ApiFingerprint,
        [Parameter(Mandatory = $true)][string]$BearerToken
    )

    $RepositoryRef = ([string]$RepositoryRef).Trim().ToLowerInvariant()
    if ($RepositoryRef -notmatch '^[0-9a-f]{40}$') {
        throw 'RepositoryRef must be an immutable 40-character SHA.'
    }
    $ExpectedSha256 = (([string]$ExpectedSha256) -replace '[^0-9A-Fa-f]', '').ToLowerInvariant()
    if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Bakunity Transport artifact checksum is invalid.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Bakunity Transport currently requires Windows x64.'
    }
    $Arch = "$env:PROCESSOR_ARCHITECTURE $env:PROCESSOR_ARCHITEW6432".ToUpperInvariant()
    if ($Arch.Contains('ARM64')) {
        throw 'Bakunity Transport ARM64 build is not enabled yet.'
    }

    $ExistingRef = if (Test-Path -LiteralPath $script:BakunityNativeTransportRef) {
        (Get-Content -LiteralPath $script:BakunityNativeTransportRef -Raw).Trim().ToLowerInvariant()
    } else { '' }
    $ExistingHash = if (Test-Path -LiteralPath $script:BakunityNativeTransportExe) {
        (Get-FileHash -LiteralPath $script:BakunityNativeTransportExe -Algorithm SHA256).Hash.ToLowerInvariant()
    } else { '' }
    if ($ExistingRef -eq $RepositoryRef -and $ExistingHash -eq $ExpectedSha256) {
        return
    }

    $Work = Join-Path ([IO.Path]::GetTempPath()) ('BakunityTransportDownload-' + [Guid]::NewGuid().ToString('N'))
    $Candidate = Join-Path $Work 'BakunityTransport.exe'
    New-Item -ItemType Directory -Path $Work -Force | Out-Null
    try {
        Save-BakunityNativeTransportArtifact -DownloadUrl $DownloadUrl -ApiFingerprint $ApiFingerprint -BearerToken $BearerToken -OutputPath $Candidate

        if (-not (Test-Path -LiteralPath $Candidate)) {
            throw 'Bakunity Transport artifact was not downloaded.'
        }
        $ActualSha256 = (Get-FileHash -LiteralPath $Candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualSha256 -ne $ExpectedSha256) {
            throw 'Bakunity Transport artifact checksum mismatch.'
        }

        New-Item -ItemType Directory -Path $script:BakunityNativeTransportRoot -Force | Out-Null
        Stop-BakunityNativeTransportTask
        Copy-Item -LiteralPath $Candidate -Destination $script:BakunityNativeTransportExe -Force
        Set-BakunityNativeExecutableAcl -Path $script:BakunityNativeTransportExe
        Set-Content -LiteralPath $script:BakunityNativeTransportRef -Value $RepositoryRef -Encoding ASCII
        Set-BakunityNativeSecretAcl -Path $script:BakunityNativeTransportRef

        foreach ($Name in @('Bakunity Transport TCP', 'Bakunity Transport UDP')) {
            Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
        }
        New-NetFirewallRule -DisplayName 'Bakunity Transport TCP' -Direction Inbound -Action Allow -Program $script:BakunityNativeTransportExe -Protocol TCP -Profile Any | Out-Null
        New-NetFirewallRule -DisplayName 'Bakunity Transport UDP' -Direction Inbound -Action Allow -Program $script:BakunityNativeTransportExe -Protocol UDP -Profile Any | Out-Null

        $StaleBefore = (Get-Date).AddHours(-1)
        $LegacyRoot = Join-Path $env:WINDIR 'SystemTemp'
        Get-ChildItem -LiteralPath $LegacyRoot -Directory -Filter 'BakunityTransportBuild-*' -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $StaleBefore } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    finally {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Set-BakunityNativeTransportConfig {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('host','connector','both')]
        [string]$Role,

        [Parameter(Mandatory = $true)]
        [string]$RelayAddr,

        [string]$SharedSecret = ''
    )

    if ([string]::IsNullOrWhiteSpace($RelayAddr)) {
        throw 'Bakunity Transport relay address is required.'
    }
    if ($Role -in @('host','both') -and [string]::IsNullOrWhiteSpace($SharedSecret)) {
        throw 'Bakunity Transport Host secret is required.'
    }

    New-Item -ItemType Directory -Path $script:BakunityNativeTransportRoot -Force | Out-Null
    $ConfigTemp = "$script:BakunityNativeTransportConfig.tmp"
    $ConfigJson = [ordered]@{
        role = $Role
        identity_path = (
            Join-Path $script:BakunityNativeTransportRoot 'identity.key'
        )
        relay_addr = $RelayAddr
        control_addr = '127.0.0.1:48389'
        target = '127.0.0.1:3389'
        shared_secret = $SharedSecret
    } | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText(
        $ConfigTemp,
        $ConfigJson,
        (New-Object Text.UTF8Encoding($false))
    )
    Set-BakunityNativeSecretAcl -Path $ConfigTemp
    Move-Item -LiteralPath $ConfigTemp -Destination $script:BakunityNativeTransportConfig -Force
}

function Start-BakunityNativeTransport {
    if (-not (Test-Path -LiteralPath $script:BakunityNativeTransportExe)) {
        throw 'Bakunity Transport executable is missing.'
    }
    if (-not (Test-Path -LiteralPath $script:BakunityNativeTransportConfig)) {
        throw 'Bakunity Transport config is missing.'
    }

    Stop-BakunityNativeTransportTask
    Unregister-ScheduledTask -TaskName $script:BakunityNativeTransportTask -Confirm:$false -ErrorAction SilentlyContinue

    $Args = 'node --config "' + $script:BakunityNativeTransportConfig + '"'
    $Action = New-ScheduledTaskAction -Execute $script:BakunityNativeTransportExe -Argument $Args
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT10S'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $script:BakunityNativeTransportTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    Start-ScheduledTask -TaskName $script:BakunityNativeTransportTask

    $Deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $Status = Get-BakunityNativeTransportStatus
        if ($Status -and [bool]$Status.ok) {
            return $Status
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $Deadline)

    throw 'Bakunity Transport did not become healthy.'
}

function Set-BakunityNativeForward {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$PeerId,
        [Parameter(Mandatory = $true)][string]$SharedSecret,
        [Parameter(Mandatory = $true)][string]$Listen,
        [ValidateSet('auto','direct')][string]$Mode = 'auto'
    )

    $Body = @{
        key = $Key
        peer_id = $PeerId
        shared_secret = $SharedSecret
        listen = $Listen
        mode = $Mode
    } | ConvertTo-Json -Compress

    return Invoke-RestMethod -UseBasicParsing -Method Post -Uri (
        $script:BakunityNativeTransportControl + '/forward'
    ) -ContentType 'application/json' -Body $Body -TimeoutSec 10
}
