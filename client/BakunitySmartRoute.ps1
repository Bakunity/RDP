param(
    [switch]$Once
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$BaseDir = 'C:\ProgramData\BakunityRDP\SmartRoute'
$ConfigPath = Join-Path $BaseDir 'config.json'
$StatePath = Join-Path $BaseDir 'state.json'
$MeshLibPath = Join-Path $BaseDir 'BakunityMesh.ps1'
$NativeTransportLibPath = Join-Path $BaseDir 'BakunityNativeTransport.ps1'
$LogPath = Join-Path $BaseDir 'smart-route.log'
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$HostsBegin = '# BEGIN BAKUNITY RDP SMART ROUTE'
$HostsEnd = '# END BAKUNITY RDP SMART ROUTE'
$SyncIntervalSeconds = 15
$TransparentPort = 3389
$LauncherPortStart = 43000
$NativeForwardPortStart = 45000

function Write-Log {
    param([string]$Message)
    $Line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    if ($Once) { Write-Host $Line }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-JsonFile {
    param([string]$Path, [object]$Value)
    $Temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $Temp -Encoding UTF8
    $Acl = Get-Acl -LiteralPath $Temp
    $Acl.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)')
    Set-Acl -LiteralPath $Temp -AclObject $Acl
    Move-Item -LiteralPath $Temp -Destination $Path -Force
}

function Normalize-Fingerprint {
    param([string]$Value)
    return (($Value -replace '[^0-9A-Fa-f]', '').ToUpperInvariant())
}

$PinnedHttpClientSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace BakunityRdpSmartRoute
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
                    return String.Equals(actual, expected, StringComparison.OrdinalIgnoreCase);
                }
            };
            var client = new HttpClient(handler);
            client.Timeout = TimeSpan.FromSeconds(45);
            return client;
        }
    }
}
'@

if (-not ('BakunityRdpSmartRoute.PinnedHttpClientFactory' -as [type])) {
    Add-Type -TypeDefinition $PinnedHttpClientSource -Language CSharp -ReferencedAssemblies 'System.Net.Http.dll'
}

function New-PinnedClient {
    param([object]$Config)
    $Fingerprint = Normalize-Fingerprint -Value ([string]$Config.api_fingerprint)
    if ($Fingerprint.Length -ne 64) { throw 'Smart Route API fingerprint is invalid.' }
    return [BakunityRdpSmartRoute.PinnedHttpClientFactory]::Create($Fingerprint)
}

function Invoke-ControlGet {
    param([object]$Config, [string]$Path)
    $Client = New-PinnedClient -Config $Config
    $Request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, "$(([string]$Config.api_base_url).TrimEnd('/'))$Path")
    $Request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', [string]$Config.access_token)
    try {
        try {
            $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        }
        catch {
            throw "Smart Route API GET $Path failed: $($_.Exception.GetBaseException().Message)"
        }
        try {
            $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $Response.IsSuccessStatusCode) { throw "Smart Route API HTTP $([int]$Response.StatusCode): $Text" }
            return $Text | ConvertFrom-Json
        }
        finally { $Response.Dispose() }
    }
    finally {
        $Request.Dispose()
        $Client.Dispose()
    }
}

function Invoke-ControlPost {
    param([object]$Config, [string]$Path, [object]$Body)
    $Client = New-PinnedClient -Config $Config
    $Request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, "$(([string]$Config.api_base_url).TrimEnd('/'))$Path")
    $Request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', [string]$Config.access_token)
    $Json = $Body | ConvertTo-Json -Depth 16 -Compress
    $Request.Content = New-Object System.Net.Http.StringContent($Json, [Text.Encoding]::UTF8, 'application/json')
    try {
        try {
            $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        }
        catch {
            throw "Smart Route API POST $Path failed: $($_.Exception.GetBaseException().Message)"
        }
        try {
            $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $Response.IsSuccessStatusCode) { throw "Smart Route telemetry HTTP $([int]$Response.StatusCode): $Text" }
            return $Text | ConvertFrom-Json
        }
        finally { $Response.Dispose() }
    }
    finally {
        $Request.Dispose()
        $Client.Dispose()
    }
}

function Get-NativeSystem32 {
    $System32 = Join-Path $env:WINDIR 'System32'
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) { $System32 = Join-Path $env:WINDIR 'Sysnative' }
    return $System32
}

$NativeSystem32 = Get-NativeSystem32
$Netsh = Join-Path $NativeSystem32 'netsh.exe'
$Ipconfig = Join-Path $NativeSystem32 'ipconfig.exe'

function Test-LoopbackAddress {
    param([string]$Address)
    return [bool]($Address -match '^127\.77\.(?:\d{1,3})\.(?:\d{1,3})$')
}

function Get-FreeLoopbackAddress {
    param([System.Collections.Generic.HashSet[string]]$Used)
    for ($Index = 0; $Index -lt (255 * 254); $Index++) {
        $Third = [Math]::Floor($Index / 254)
        $Fourth = ($Index % 254) + 1
        $Candidate = "127.77.$Third.$Fourth"
        if (-not $Used.Contains($Candidate)) {
            [void]$Used.Add($Candidate)
            return $Candidate
        }
    }
    throw 'Smart Route loopback address pool is exhausted.'
}

function Remove-ManagedHostsBlock {
    param([string]$Text)
    $Pattern = '(?ms)^\s*' + [regex]::Escape($HostsBegin) + '\s*\r?\n.*?^\s*' + [regex]::Escape($HostsEnd) + '\s*(?:\r?\n)?'
    return [regex]::Replace($Text, $Pattern, '')
}

function Write-ManagedHosts {
    param([array]$Mappings)
    $Original = if (Test-Path -LiteralPath $HostsPath) { [IO.File]::ReadAllText($HostsPath) } else { '' }
    $Unmanaged = Remove-ManagedHostsBlock -Text $Original
    $Lines = @($HostsBegin)
    foreach ($Mapping in @($Mappings | Sort-Object hostname)) {
        $Lines += "$($Mapping.loopback)$([char]9)$($Mapping.hostname) # $($Mapping.device_id)"
    }
    $Lines += $HostsEnd
    $Block = ($Lines -join [Environment]::NewLine) + [Environment]::NewLine
    $Prefix = $Unmanaged.TrimEnd([char]13, [char]10)
    $Text = if ($Prefix) { $Prefix + [Environment]::NewLine + [Environment]::NewLine + $Block } else { $Block }
    [IO.File]::WriteAllText($HostsPath, $Text, (New-Object Text.UTF8Encoding($false)))
    & $Ipconfig /flushdns | Out-Null
}

function Test-TcpCandidate {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 800)
    if ([string]::IsNullOrWhiteSpace($HostName)) { return $null }
    $Watch = [Diagnostics.Stopwatch]::StartNew()
    $Client = New-Object Net.Sockets.TcpClient
    try {
        $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $Async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $null }
        $Client.EndConnect($Async)
        $Watch.Stop()
        return [int][Math]::Max(1, $Watch.ElapsedMilliseconds)
    }
    catch { return $null }
    finally {
        $Watch.Stop()
        $Client.Dispose()
    }
}

function Resolve-IPv4 {
    param([string]$HostName)
    $Parsed = $null
    if ([Net.IPAddress]::TryParse($HostName, [ref]$Parsed) -and $Parsed.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) { return $Parsed.IPAddressToString }
    $Address = @([Net.Dns]::GetHostAddresses($HostName) | Where-Object { $_.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork }) | Select-Object -First 1
    if (-not $Address) { throw "No IPv4 address for $HostName" }
    return $Address.IPAddressToString
}

function Get-RoutingMode {
    $Listeners = @(Get-NetTCPConnection -LocalPort 3389 -State Listen -ErrorAction SilentlyContinue)
    foreach ($Listener in $Listeners) {
        if ([string]$Listener.LocalAddress -in @('0.0.0.0','::','::0','127.0.0.1')) { return 'launcher' }
    }
    return 'transparent'
}

function Select-DeviceRoute {
    param(
        [object]$Device,
        [string]$Policy,
        [int]$NativePort
    )

    if ($Policy -in @('auto','lan')) {
        foreach ($Lan in @($Device.routes.lan)) {
            if (-not $Lan -or -not $Lan.host) { continue }
            $Latency = Test-TcpCandidate -HostName ([string]$Lan.host) -Port ([int]$Lan.port)
            if ($null -ne $Latency) {
                return [pscustomobject]@{
                    type='lan'
                    host=[string]$Lan.host
                    target_ipv4=(Resolve-IPv4 -HostName ([string]$Lan.host))
                    target_port=[int]$Lan.port
                    latency_ms=[int]$Latency
                    reason='lan_direct'
                }
            }
        }
        if ($Policy -eq 'lan') {
            return [pscustomobject]@{
                type='unavailable'; host=''; target_ipv4=''; target_port=0
                latency_ms=0; reason='no reachable LAN route'
            }
        }
    }

    if ($Policy -in @('auto','p2p')) {
        $Native = $Device.routes.native
        if (
            $Native -and
            [bool]$Native.available -and
            $Native.peer_id -and
            $Native.shared_secret
        ) {
            $NativeMode = 'auto'
            if ($Policy -eq 'p2p') {
                $NativeMode = 'direct'
            }
            try {
                $Forward = Set-BakunityNativeForward -Key ([string]$Device.id) -PeerId ([string]$Native.peer_id) -SharedSecret ([string]$Native.shared_secret) -Listen "127.0.0.1:$NativePort" -Mode $NativeMode
                if ($Forward -and [bool]$Forward.ok) {
                    $NativePath = [string]$Forward.path
                    $NativeType = 'native_auto'
                    $NativeReason = 'bakunity_native_auto'
                    if ($NativePath -eq 'direct') {
                        $NativeType = 'native_p2p'
                        $NativeReason = 'bakunity_p2p_direct'
                    }
                    elseif ($NativePath -eq 'relay') {
                        $NativeType = 'native_relay'
                        $NativeReason = 'bakunity_relay'
                    }
                    return [pscustomobject]@{
                        type = $NativeType
                        host = '127.0.0.1'
                        target_ipv4 = '127.0.0.1'
                        target_port = [int]$NativePort
                        latency_ms = 0
                        reason = $NativeReason
                    }
                }
            }
            catch {
                Write-Log "NATIVE_FORWARD=ERROR device=$($Device.id) $($_.Exception.Message)"
                if ($Policy -eq 'p2p') {
                    return [pscustomobject]@{
                        type='unavailable'; host=''; target_ipv4=''; target_port=0
                        latency_ms=0; reason='Bakunity direct path unavailable'
                    }
                }
            }
        }
    }

    if ($Policy -in @('auto','p2p')) {
        $P2p = $Device.routes.p2p
        if ($P2p -and [bool]$P2p.available -and $P2p.host) {
            $Path = Test-BakunityMeshDirect -Target ([string]$P2p.host)
            if ($Path.direct) {
                $TcpLatency = Test-TcpCandidate -HostName ([string]$P2p.host) -Port ([int]$P2p.port)
                if ($null -ne $TcpLatency) {
                    return [pscustomobject]@{
                        type='p2p'
                        host=[string]$P2p.host
                        target_ipv4=(Resolve-IPv4 -HostName ([string]$P2p.host))
                        target_port=[int]$P2p.port
                        latency_ms=[int]$TcpLatency
                        reason='p2p_direct'
                    }
                }
            }
            if ($Policy -eq 'p2p') {
                $Reason = if ($Path.peer_relay) {
                    'peer relay only'
                } elseif ($Path.relay) {
                    'DERP relay only'
                } else {
                    'direct mesh path unavailable'
                }
                return [pscustomobject]@{
                    type='unavailable'; host=''; target_ipv4=''; target_port=0
                    latency_ms=0; reason=$Reason
                }
            }
        }
        elseif ($Policy -eq 'p2p') {
            return [pscustomobject]@{
                type='unavailable'; host=''; target_ipv4=''; target_port=0
                latency_ms=0; reason='Host mesh route unavailable'
            }
        }
    }

    if ($Policy -in @('auto','relay')) {
        $Relay = $Device.routes.relay
        if ($Relay -and [bool]$Relay.available -and $Relay.host) {
            $Latency = Test-TcpCandidate -HostName ([string]$Relay.host) -Port ([int]$Relay.port)
            if ($null -ne $Latency) {
                return [pscustomobject]@{
                    type='relay'
                    host=[string]$Relay.host
                    target_ipv4=(Resolve-IPv4 -HostName ([string]$Relay.host))
                    target_port=[int]$Relay.port
                    latency_ms=[int]$Latency
                    reason='vps_relay'
                }
            }
        }
    }

    return [pscustomobject]@{
        type='unavailable'; host=''; target_ipv4=''; target_port=0
        latency_ms=0; reason="no reachable $Policy route"
    }
}

function Remove-PortProxy {
    param([string]$ListenAddress, [int]$ListenPort)
    & $Netsh interface portproxy delete v4tov4 listenaddress=$ListenAddress listenport=$ListenPort protocol=tcp *> $null
}

function Set-PortProxy {
    param([string]$ListenAddress, [int]$ListenPort, [string]$TargetIPv4, [int]$TargetPort)
    Remove-PortProxy -ListenAddress $ListenAddress -ListenPort $ListenPort
    if (-not $TargetIPv4 -or $TargetPort -le 0) { return }
    $Output = @(& $Netsh interface portproxy add v4tov4 listenaddress=$ListenAddress listenport=$ListenPort connectaddress=$TargetIPv4 connectport=$TargetPort protocol=tcp 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "portproxy failed: $($Output -join ' ')" }
}

function Get-ExistingMap {
    param([object]$State)
    $Result = @{}
    if ($State -and $State.mappings) {
        foreach ($Property in $State.mappings.PSObject.Properties) { $Result[$Property.Name] = $Property.Value }
    }
    return $Result
}

function Build-Mappings {
    param([object]$Manifest, [object]$State)
    $DefaultPolicy = ([string]$Manifest.connector.route_policy).Trim().ToLowerInvariant()
    if ($DefaultPolicy -notin @('auto','p2p','relay','lan')) { $DefaultPolicy = 'auto' }
    $Mode = Get-RoutingMode
    $Existing = Get-ExistingMap -State $State
    $Used = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($Entry in $Existing.Values) {
        if (Test-LoopbackAddress -Address ([string]$Entry.loopback)) { [void]$Used.Add([string]$Entry.loopback) }
    }
    $Mappings = @()
    $Index = 0
    foreach ($Device in @($Manifest.devices | Sort-Object id)) {
        $Id = [string]$Device.id
        if ($Id -notmatch '^[0-9a-fA-F]{32}$') { throw "Invalid device id: $Id" }
        $Loopback = ''
        if ($Existing.ContainsKey($Id)) {
            $Candidate = [string]$Existing[$Id].loopback
            if (Test-LoopbackAddress -Address $Candidate) { $Loopback = $Candidate }
        }
        if (-not $Loopback) { $Loopback = Get-FreeLoopbackAddress -Used $Used }
        $Policy = ([string]$Device.route_policy).Trim().ToLowerInvariant()
        if ($Policy -notin @('auto','p2p','relay','lan')) {
            $Policy = $DefaultPolicy
        }
        $NativePort = $NativeForwardPortStart + $Index
        $Route = Select-DeviceRoute -Device $Device -Policy $Policy -NativePort $NativePort
        $LocalPort = if ($Mode -eq 'transparent') { $TransparentPort } else { $LauncherPortStart + $Index }
        $Mappings += [pscustomobject]@{
            device_id=$Id
            hostname=[string]$Device.hostname
            loopback=$Loopback
            local_port=[int]$LocalPort
            enabled=[bool]$Device.enabled
            route_policy=[string]$Policy
            route_type=[string]$Route.type
            target_ipv4=[string]$Route.target_ipv4
            target_port=[int]$Route.target_port
            latency_ms=[int]$Route.latency_ms
            reason=[string]$Route.reason
        }
        $Index++
    }
    return [pscustomobject]@{ policy=$DefaultPolicy; mode=$Mode; mappings=@($Mappings) }
}

function Sync-ConnectorNativeTransport {
    param([object]$Config, [object]$Manifest)

    $NativeServer = $Manifest.server.native_transport
    if (-not $NativeServer -or -not [bool]$NativeServer.enabled) {
        return Get-BakunityNativeTransportStatus
    }

    $RepositoryRef = ([string]$Config.repository_ref).Trim().ToLowerInvariant()
    if ($RepositoryRef -notmatch '^[0-9a-f]{40}$') {
        throw 'Connector repository ref is unavailable for native transport.'
    }

    $Status = Get-BakunityNativeTransportStatus
    $NativeRole = if ($Status) { [string]$Status.role } else { '' }
    $InstalledRef = Get-BakunityNativeTransportBuildRef
    $NeedsNativeConfig = [bool](
        -not $Status -or
        -not [bool]$Status.ok -or
        $NativeRole -notin @('connector','both')
    )
    $NeedsNativeBinary = [bool](
        $InstalledRef -ne $RepositoryRef
    )

    if ($NeedsNativeConfig -or $NeedsNativeBinary) {
        $Bootstrap = Invoke-ControlPost -Config $Config -Path '/v1/named-access/native-transport-bootstrap' -Body @{}
        if ($Bootstrap -and [bool]$Bootstrap.enabled) {
            $Artifact = $Bootstrap.windows_amd64
            if (-not $Artifact) {
                throw 'Windows native transport artifact is unavailable.'
            }
            if (
                ([string]$Artifact.repository_ref).ToLowerInvariant() -ne
                $RepositoryRef
            ) {
                throw 'Windows native transport artifact ref mismatch.'
            }

            $DownloadUrl = (
                ([string]$Config.api_base_url).TrimEnd('/') +
                [string]$Artifact.download_path
            )
            Install-BakunityNativeTransportBinary -RepositoryRef $RepositoryRef -DownloadUrl $DownloadUrl -ExpectedSha256 ([string]$Artifact.sha256) -ApiFingerprint ([string]$Config.api_fingerprint) -BearerToken ([string]$Config.access_token)

            # A PC can be both an RDP host and a connector. If its existing
            # Native config already has role=both, keep that config and its
            # host secret intact while replacing/restarting only the binary.
            if ($NeedsNativeConfig) {
                Set-BakunityNativeTransportConfig -Role connector -RelayAddr ([string]$Bootstrap.relay_addr)
            }
            $Status = Start-BakunityNativeTransport
            Write-Log "NATIVE_TRANSPORT=ONLINE peer=$([string]$Status.peer_id) ref=$RepositoryRef role=$([string]$Status.role)"
        }
    }
    return Get-BakunityNativeTransportStatus
}

function Test-ConnectorMeshRole {
    param([object]$Mesh)
    return [bool](@($Mesh.roles) -contains 'connector')
}

function Sync-ConnectorMesh {
    param([object]$Config, [object]$Manifest)

    $Enabled = [bool]$Manifest.server.smart_route.enabled
    if (-not $Enabled) {
        return Get-BakunityTailscaleStatus
    }

    $Mesh = Get-BakunityTailscaleStatus
    if (-not $Mesh.installed) {
        Write-Log 'MESH=SKIPPED Tailscale is not installed; native transport and OpenSSH fallback remain available'
        return $Mesh
    }
    if ($Mesh.conflict) {
        Write-Log 'MESH=CONFLICT foreign Tailscale detected; Relay remains available'
        return $Mesh
    }

    $NeedsEnrollment = [bool](
        -not $Mesh.online -or
        -not (Test-ConnectorMeshRole -Mesh $Mesh) -or
        [string]$Mesh.control_url -ne [string]$Manifest.server.smart_route.control_url
    )
    if ($NeedsEnrollment) {
        $Bootstrap = Invoke-ControlPost -Config $Config -Path '/v1/named-access/mesh-bootstrap' -Body @{}
        if ($Bootstrap -and [bool]$Bootstrap.enabled) {
            $Result = Ensure-BakunityMeshRole -Role connector -Bootstrap $Bootstrap
            if ($Result.conflict) {
                Write-Log 'MESH=CONFLICT foreign Tailscale detected'
            }
            else {
                Write-Log 'MESH=ONLINE role=connector'
            }
        }
    }
    return Get-BakunityTailscaleStatus
}

function Sync-SmartRoute {
    $Config = Read-JsonFile -Path $ConfigPath
    if (-not $Config) { throw "Missing Smart Route config: $ConfigPath" }
    $Manifest = Invoke-ControlGet -Config $Config -Path '/v1/named-access/manifest'
    if (-not $Manifest.ok -or [int]$Manifest.manifest_version -ne 2) { throw 'Smart Route manifest v2 is required.' }
    $NativeStatus = Sync-ConnectorNativeTransport -Config $Config -Manifest $Manifest
    $Mesh = Sync-ConnectorMesh -Config $Config -Manifest $Manifest
    $State = Read-JsonFile -Path $StatePath
    $Built = Build-Mappings -Manifest $Manifest -State $State
    $Mappings = @($Built.mappings)

    $IpHelper = Get-Service -Name iphlpsvc -ErrorAction Stop
    if ($IpHelper.Status -ne 'Running') { Start-Service -Name iphlpsvc -ErrorAction Stop }

    $Old = Get-ExistingMap -State $State
    foreach ($Entry in $Old.Values) {
        $Address = [string]$Entry.loopback
        $Port = if ($Entry.PSObject.Properties['local_port']) { [int]$Entry.local_port } else { 3389 }
        if (Test-LoopbackAddress -Address $Address) { Remove-PortProxy -ListenAddress $Address -ListenPort $Port }
    }
    foreach ($Mapping in $Mappings) {
        Set-PortProxy -ListenAddress ([string]$Mapping.loopback) -ListenPort ([int]$Mapping.local_port) -TargetIPv4 ([string]$Mapping.target_ipv4) -TargetPort ([int]$Mapping.target_port)
    }
    Write-ManagedHosts -Mappings $Mappings

    $MapState = [ordered]@{}
    $RouteTelemetry = [ordered]@{}
    foreach ($Mapping in $Mappings) {
        $MapState[[string]$Mapping.device_id] = [ordered]@{
            hostname=[string]$Mapping.hostname
            loopback=[string]$Mapping.loopback
            local_port=[int]$Mapping.local_port
            enabled=[bool]$Mapping.enabled
            route_policy=[string]$Mapping.route_policy
            route_type=[string]$Mapping.route_type
            target_ipv4=[string]$Mapping.target_ipv4
            target_port=[int]$Mapping.target_port
            latency_ms=[int]$Mapping.latency_ms
            reason=[string]$Mapping.reason
        }
        $RouteTelemetry[[string]$Mapping.device_id] = [ordered]@{
            hostname=[string]$Mapping.hostname
            policy=[string]$Mapping.route_policy
            route=[string]$Mapping.route_type
            latency_ms=[int]$Mapping.latency_ms
            reason=[string]$Mapping.reason
            active_sessions=0
            last_stream_path=''
            last_stream_at=0
        }
    }

    $Tail = Get-BakunityTailscaleStatus
    if ($NativeStatus -and $NativeStatus.forwards) {
        foreach ($Forward in @($NativeStatus.forwards)) {
            $Key = [string]$Forward.key
            if (-not $RouteTelemetry.Contains($Key)) {
                continue
            }
            $Path = [string]$Forward.path
            $ActiveSessions = 0
            try { $ActiveSessions = [int]$Forward.active_sessions } catch { $ActiveSessions = 0 }
            $LastStreamPath = [string]$Forward.last_stream_path
            $LastStreamAt = 0
            try { $LastStreamAt = [int64]$Forward.last_stream_at } catch { $LastStreamAt = 0 }

            $RouteTelemetry[$Key].active_sessions = [int]$ActiveSessions
            $RouteTelemetry[$Key].last_stream_path = $LastStreamPath
            $RouteTelemetry[$Key].last_stream_at = [int64]$LastStreamAt

            $EffectivePath = $Path
            if ($ActiveSessions -gt 0 -and $LastStreamPath -in @('direct','relay')) {
                $EffectivePath = $LastStreamPath
            }
            if ($EffectivePath -eq 'direct') {
                $RouteTelemetry[$Key].route = 'native_p2p'
                $RouteTelemetry[$Key].reason = 'bakunity_p2p_direct'
            }
            elseif ($EffectivePath -eq 'relay') {
                $RouteTelemetry[$Key].route = 'native_relay'
                $RouteTelemetry[$Key].reason = 'bakunity_relay'
            }
        }
    }

    Write-JsonFile -Path $StatePath -Value ([ordered]@{
        version=4
        connector_id=[string]$Manifest.connector.id
        connector_name=[string]$Manifest.connector.name
        route_policy=[string]$Built.policy
        routing_mode=[string]$Built.mode
        device_domain=[string]$Manifest.server.device_domain
        updated_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        mappings=$MapState
    })

    [void](Invoke-ControlPost -Config $Config -Path '/v1/named-access/telemetry' -Body @{
        machine_name=$env:COMPUTERNAME
        telemetry=[ordered]@{
            captured_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            routing_mode=[string]$Built.mode
            route_policy=[string]$Built.policy
            native_transport=[ordered]@{
                installed=[bool](Test-Path -LiteralPath $script:BakunityNativeTransportExe)
                online=[bool]($NativeStatus -and $NativeStatus.ok)
                peer_id=[string]$NativeStatus.peer_id
                relay_connected=[bool]($NativeStatus -and $NativeStatus.relay_connected)
                version=[string]$NativeStatus.version
            }
            mesh=$Tail
            routes=$RouteTelemetry
        }
    })

    $Summary = @($Mappings | Group-Object route_type | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ' '
    Write-Log "SYNC=PASS policy=$($Built.policy) mode=$($Built.mode) $Summary"
}

New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $MeshLibPath)) {
    throw "Missing mesh library: $MeshLibPath"
}
if (-not (Test-Path -LiteralPath $NativeTransportLibPath)) {
    throw "Missing native transport library: $NativeTransportLibPath"
}
. $MeshLibPath
. $NativeTransportLibPath
$Mutex = New-Object Threading.Mutex($false, 'Global\BakunityRdpSmartRoute')
$HasMutex = $false
try {
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        if ($Once) { Write-Host 'SMART_ROUTE=ALREADY_RUNNING' }
        exit 0
    }
    do {
        try {
            Sync-SmartRoute
            if ($Once) { Write-Host 'SMART_ROUTE=PASS' }
        }
        catch {
            Write-Log "SYNC=ERROR $($_.Exception.Message)"
            if ($Once) {
                Write-Host "SMART_ROUTE=ERROR:$($_.Exception.Message)"
                exit 1
            }
        }
        if ($Once) { break }
        Start-Sleep -Seconds $SyncIntervalSeconds
    } while ($true)
}
finally {
    if ($HasMutex) {
        try { $Mutex.ReleaseMutex() } catch {}
    }
    $Mutex.Dispose()
}
