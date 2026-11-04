param([switch]$Once)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$HermesDir = 'C:\ProgramData\HermesRDP'
$BaseDir = Join-Path $HermesDir 'SmartRoute'
$ConfigPath = Join-Path $HermesDir 'device.json'
$MeshLibPath = Join-Path $BaseDir 'BakunityMesh.ps1'
$LogPath = Join-Path $BaseDir 'host-smart-route.log'
$PollSeconds = 15

function Write-HostRouteLog {
    param([string]$Message)
    $Line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    if ($Once) { Write-Host $Line }
}

function Read-Json {
    param([string]$Path)
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

$PinnedSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace BakunityRdpHostRoute
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
                        actual, expected, StringComparison.OrdinalIgnoreCase
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

if (-not ('BakunityRdpHostRoute.PinnedHttpClientFactory' -as [type])) {
    Add-Type -TypeDefinition $PinnedSource -Language CSharp -ReferencedAssemblies 'System.Net.Http.dll'
}

function Invoke-PinnedPost {
    param([object]$Config, [string]$Path, [object]$Body)

    $Client = [BakunityRdpHostRoute.PinnedHttpClientFactory]::Create(
        [string]$Config.api_fingerprint
    )
    $Url = "$(([string]$Config.api_base_url).TrimEnd('/'))$Path"
    $Request = New-Object System.Net.Http.HttpRequestMessage(
        [System.Net.Http.HttpMethod]::Post,
        $Url
    )
    $Request.Headers.Authorization =
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue(
            'Bearer',
            [string]$Config.device_token
        )
    $Json = $Body | ConvertTo-Json -Depth 12 -Compress
    $Request.Content = New-Object System.Net.Http.StringContent(
        $Json,
        [Text.Encoding]::UTF8,
        'application/json'
    )
    try {
        $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        try {
            $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $Response.IsSuccessStatusCode) {
                throw "HTTP $([int]$Response.StatusCode): $Text"
            }
            if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
            return $Text | ConvertFrom-Json
        }
        finally { $Response.Dispose() }
    }
    finally {
        $Request.Dispose()
        $Client.Dispose()
    }
}

function Get-LanIPv4 {
    $Result = @()
    try {
        foreach ($Item in @(
            Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.AddressState -eq 'Preferred' }
        )) {
            $Address = [string]$Item.IPAddress
            if (
                $Address -match '^10\.' -or
                $Address -match '^192\.168\.' -or
                $Address -match '^172\.(1[6-9]|2[0-9]|3[01])\.'
            ) {
                $Result += $Address
            }
        }
    }
    catch {}
    return @($Result | Sort-Object -Unique)
}

function New-SmartRouteTelemetry {
    $Mesh = Get-BakunityTailscaleStatus
    return [ordered]@{
        captured_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        lan_ipv4 = @(Get-LanIPv4)
        mesh_installed = [bool]$Mesh.installed
        mesh_online = [bool]$Mesh.online
        mesh_ipv4 = [string]$Mesh.ipv4
        mesh_conflict = [bool]$Mesh.conflict
        mesh_version = [string]$Mesh.version
    }
}

function Test-HasMeshRole {
    param([object]$Mesh, [string]$Role)
    return [bool](@($Mesh.roles) -contains $Role)
}

function Sync-HostSmartRoute {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw "Missing Host config: $ConfigPath"
    }
    if (-not (Test-Path -LiteralPath $MeshLibPath)) {
        throw "Missing mesh library: $MeshLibPath"
    }

    $Config = Read-Json -Path $ConfigPath
    $DeviceId = [string]$Config.device_id
    if ($DeviceId -notmatch '^[0-9a-fA-F]{32}$') {
        throw 'Invalid Host device id.'
    }

    $Telemetry = New-SmartRouteTelemetry
    $Response = Invoke-PinnedPost -Config $Config -Path "/v1/devices/$DeviceId/smart-route-telemetry" -Body @{ smart_route = $Telemetry }

    if ($Response -and [bool]$Response.mesh_enabled) {
        $Mesh = Get-BakunityTailscaleStatus
        $NeedsEnrollment = [bool](
            -not $Mesh.conflict -and (
                -not $Mesh.online -or
                -not (Test-HasMeshRole -Mesh $Mesh -Role 'host') -or
                [string]$Mesh.control_url -ne [string]$Response.control_url
            )
        )

        if ($NeedsEnrollment) {
            $Bootstrap = Invoke-PinnedPost -Config $Config -Path "/v1/devices/$DeviceId/smart-route-bootstrap" -Body @{}
            if ($Bootstrap -and [bool]$Bootstrap.enabled) {
                $Result = Ensure-BakunityMeshRole -Role host -Bootstrap $Bootstrap
                if ($Result.conflict) {
                    Write-HostRouteLog 'MESH=CONFLICT foreign Tailscale detected'
                }
                else {
                    Write-HostRouteLog 'MESH=ONLINE role=host'
                }
            }
        }

        $Telemetry = New-SmartRouteTelemetry
        [void](Invoke-PinnedPost -Config $Config -Path "/v1/devices/$DeviceId/smart-route-telemetry" -Body @{ smart_route = $Telemetry })
    }

    $Final = Get-BakunityTailscaleStatus
    $LanCount = @(Get-LanIPv4).Count
    Write-HostRouteLog "SYNC=PASS lan=$LanCount mesh_online=$([bool]$Final.online) mesh_conflict=$([bool]$Final.conflict)"
}

New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $MeshLibPath)) {
    throw "Missing mesh library: $MeshLibPath"
}
. $MeshLibPath

$Mutex = New-Object Threading.Mutex($false, 'Global\BakunityRdpHostSmartRoute')
$HasMutex = $false
try {
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        if ($Once) { Write-Host 'HOST_SMART_ROUTE=ALREADY_RUNNING' }
        exit 0
    }

    do {
        try {
            Sync-HostSmartRoute
            if ($Once) { Write-Host 'HOST_SMART_ROUTE=PASS' }
        }
        catch {
            Write-HostRouteLog "SYNC=ERROR $($_.Exception.Message)"
            if ($Once) {
                Write-Host "HOST_SMART_ROUTE=ERROR:$($_.Exception.Message)"
                exit 1
            }
        }

        if ($Once) { break }
        Start-Sleep -Seconds $PollSeconds
    } while ($true)
}
finally {
    if ($HasMutex) {
        try { $Mutex.ReleaseMutex() } catch {}
    }
    $Mutex.Dispose()
}
