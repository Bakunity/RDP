param(
    [switch]$Once
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$BaseDir = 'C:\ProgramData\BakunityRDP\NamedAccess'
$ConfigPath = Join-Path $BaseDir 'config.json'
$StatePath = Join-Path $BaseDir 'state.json'
$LogPath = Join-Path $BaseDir 'named-access.log'
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$HostsBegin = '# BEGIN BAKUNITY RDP NAMED ACCESS'
$HostsEnd = '# END BAKUNITY RDP NAMED ACCESS'
$SyncIntervalSeconds = 60
$ListenPort = 3389

function Write-Log {
    param([string]$Message)
    $Line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    if ($Once) {
        Write-Host $Line
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-SecureJsonFile {
    param(
        [string]$Path,
        [object]$Value
    )
    $Temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $Temp -Encoding UTF8
    $Acl = Get-Acl -LiteralPath $Temp
    # The first sync can run under an elevated Administrator before the
    # LocalSystem task starts. Protect the DACL without forcing SYSTEM owner.
    $Acl.SetSecurityDescriptorSddlForm(
        'D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)'
    )
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

namespace BakunityRdpNamedAccess
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

if (-not ('BakunityRdpNamedAccess.PinnedHttpClientFactory' -as [type])) {
    Add-Type -TypeDefinition $PinnedHttpClientSource -Language CSharp -ReferencedAssemblies 'System.Net.Http.dll'
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

function Get-Manifest {
    param([object]$Config)

    $Fingerprint = Normalize-Fingerprint -Value ([string]$Config.api_fingerprint)
    if ($Fingerprint.Length -ne 64) {
        throw 'Named Access API fingerprint is invalid.'
    }
    if ([string]::IsNullOrWhiteSpace([string]$Config.access_token)) {
        throw 'Named Access access token is missing.'
    }
    $BaseUrl = ([string]$Config.api_base_url).TrimEnd('/')
    if ($BaseUrl -notmatch '^https://') {
        throw 'Named Access API URL must use HTTPS.'
    }

    $Client = [BakunityRdpNamedAccess.PinnedHttpClientFactory]::Create(
        $Fingerprint
    )
    $Request = New-Object System.Net.Http.HttpRequestMessage(
        [System.Net.Http.HttpMethod]::Get,
        "$BaseUrl/v1/named-access/manifest"
    )
    $Request.Headers.Authorization =
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue(
            'Bearer',
            [string]$Config.access_token
        )
    try {
        $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        try {
            $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $Response.IsSuccessStatusCode) {
                throw "Named Access API HTTP $([int]$Response.StatusCode): $Text"
            }
            $Payload = $Text | ConvertFrom-Json
            if (-not $Payload.ok -or [int]$Payload.manifest_version -ne 1) {
                throw 'Named Access manifest is invalid.'
            }
            return $Payload
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

function Resolve-ServerIPv4 {
    param([string]$HostName)
    $Parsed = $null
    if (
        [Net.IPAddress]::TryParse(
            $HostName,
            [ref]$Parsed
        ) -and
        $Parsed.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork
    ) {
        return $Parsed.IPAddressToString
    }

    $Address = @(
        [Net.Dns]::GetHostAddresses($HostName) |
            Where-Object {
                $_.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork
            }
    ) | Select-Object -First 1
    if (-not $Address) {
        throw "Named Access server has no IPv4 address: $HostName"
    }
    return $Address.IPAddressToString
}

function Convert-StateMappings {
    param([object]$State)
    $Result = @{}
    if ($State -and $State.mappings) {
        foreach ($Property in $State.mappings.PSObject.Properties) {
            $Result[$Property.Name] = $Property.Value
        }
    }
    return $Result
}

function Test-LoopbackAddress {
    param([string]$Address)
    $Match = [regex]::Match(
        $Address,
        '^127\.77\.(\d{1,3})\.(\d{1,3})$'
    )
    if (-not $Match.Success) {
        return $false
    }
    $Third = [int]$Match.Groups[1].Value
    $Fourth = [int]$Match.Groups[2].Value
    return (
        $Third -ge 0 -and
        $Third -le 254 -and
        $Fourth -ge 1 -and
        $Fourth -le 254
    )
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
    throw 'Named Access loopback address pool is exhausted.'
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

function Assert-NoHostsConflicts {
    param(
        [string]$UnmanagedText,
        [array]$Mappings
    )

    $Existing = New-Object 'System.Collections.Generic.HashSet[string]' (
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Line in ($UnmanagedText -split "\r?\n")) {
        $Active = ($Line -split '#', 2)[0].Trim()
        if (-not $Active) {
            continue
        }
        $Parts = @($Active -split '\s+' | Where-Object { $_ })
        if ($Parts.Count -lt 2) {
            continue
        }
        for ($Index = 1; $Index -lt $Parts.Count; $Index++) {
            [void]$Existing.Add([string]$Parts[$Index])
        }
    }

    foreach ($Mapping in $Mappings) {
        if ($Existing.Contains([string]$Mapping.hostname)) {
            throw (
                "hosts file already contains unmanaged entry for " +
                [string]$Mapping.hostname
            )
        }
    }
}

function Write-ManagedHosts {
    param(
        [string]$OriginalText,
        [array]$Mappings
    )
    $Unmanaged = Remove-ManagedHostsBlock -Text $OriginalText
    Assert-NoHostsConflicts -UnmanagedText $Unmanaged -Mappings $Mappings

    $Lines = @($HostsBegin)
    foreach ($Mapping in @($Mappings | Sort-Object hostname)) {
        $Lines += (
            "$($Mapping.loopback)`t$($Mapping.hostname) # " +
            "$($Mapping.device_id)"
        )
    }
    $Lines += $HostsEnd
    $Block = ($Lines -join [Environment]::NewLine) + [Environment]::NewLine
    $Prefix = $Unmanaged.TrimEnd("`r", "`n")
    $NewText = if ($Prefix) {
        $Prefix + [Environment]::NewLine + [Environment]::NewLine + $Block
    }
    else {
        $Block
    }

    [IO.File]::WriteAllText(
        $HostsPath,
        $NewText,
        (New-Object Text.UTF8Encoding($false))
    )
    & $Ipconfig /flushdns | Out-Null
}

function Remove-PortProxy {
    param([string]$ListenAddress)
    & $Netsh interface portproxy delete v4tov4 `
        listenaddress=$ListenAddress `
        listenport=$ListenPort `
        protocol=tcp *> $null
}

function Add-PortProxy {
    param(
        [string]$ListenAddress,
        [string]$ServerIPv4,
        [int]$RemotePort
    )
    Remove-PortProxy -ListenAddress $ListenAddress
    $Output = @(
        & $Netsh interface portproxy add v4tov4 `
            listenaddress=$ListenAddress `
            listenport=$ListenPort `
            connectaddress=$ServerIPv4 `
            connectport=$RemotePort `
            protocol=tcp 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw (
            "netsh portproxy failed for $ListenAddress`:3389 -> " +
            "$ServerIPv4`:$RemotePort : " +
            ($Output -join ' ')
        )
    }
}

function Assert-LocalRdpPortAvailable {
    param([System.Collections.Generic.HashSet[string]]$OwnedAddresses)

    $Listeners = @(
        Get-NetTCPConnection `
            -LocalPort $ListenPort `
            -State Listen `
            -ErrorAction SilentlyContinue
    )
    foreach ($Listener in $Listeners) {
        $Address = [string]$Listener.LocalAddress
        if ($OwnedAddresses.Contains($Address)) {
            continue
        }
        if (Test-LoopbackAddress -Address $Address) {
            continue
        }
        if ($Address -in @('0.0.0.0', '::', '::0', '127.0.0.1')) {
            throw (
                'Local TCP 3389 is already owned by another listener. ' +
                'Bakunity Named Access will not modify the local RDP service.'
            )
        }
    }
}

function Start-IpHelper {
    $Service = Get-Service -Name iphlpsvc -ErrorAction Stop
    if ($Service.Status -ne 'Running') {
        Start-Service -Name iphlpsvc -ErrorAction Stop
    }
}

function Build-Mappings {
    param(
        [object]$Manifest,
        [hashtable]$Existing
    )
    $Domain = [string]$Manifest.server.device_domain
    $ServerHost = [string]$Manifest.server.public_host
    if (
        [string]::IsNullOrWhiteSpace($Domain) -or
        [string]::IsNullOrWhiteSpace($ServerHost)
    ) {
        throw 'Named Access manifest server data is incomplete.'
    }
    $ServerIPv4 = Resolve-ServerIPv4 -HostName $ServerHost

    $Used = New-Object 'System.Collections.Generic.HashSet[string]' (
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Entry in $Existing.Values) {
        $Address = [string]$Entry.loopback
        if (Test-LoopbackAddress -Address $Address) {
            [void]$Used.Add($Address)
        }
    }

    $Mappings = @()
    foreach ($Device in @($Manifest.devices | Sort-Object id)) {
        $DeviceId = [string]$Device.id
        $Slug = [string]$Device.slug
        $Hostname = [string]$Device.hostname
        $RemotePort = [int]$Device.rdp_port
        if ($DeviceId -notmatch '^[0-9a-fA-F]{32}$') {
            throw "Invalid Named Access device id: $DeviceId"
        }
        if ($Slug -notmatch '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$') {
            throw "Invalid Named Access device slug: $Slug"
        }
        if (
            $Hostname -ne "$Slug.$Domain" -or
            $Hostname -notmatch '^[a-z0-9.-]+$'
        ) {
            throw "Invalid Named Access hostname: $Hostname"
        }
        if ($RemotePort -lt 1 -or $RemotePort -gt 65535) {
            throw "Invalid Named Access RDP port: $RemotePort"
        }

        $Loopback = ''
        if ($Existing.ContainsKey($DeviceId)) {
            $Candidate = [string]$Existing[$DeviceId].loopback
            if (Test-LoopbackAddress -Address $Candidate) {
                $Loopback = $Candidate
            }
        }
        if (-not $Loopback) {
            $Loopback = Get-FreeLoopbackAddress -Used $Used
        }

        $Mappings += [pscustomobject]@{
            device_id = $DeviceId
            hostname = $Hostname
            loopback = $Loopback
            server_ipv4 = $ServerIPv4
            rdp_port = $RemotePort
            enabled = [bool]$Device.enabled
        }
    }
    return $Mappings
}

function Test-MappingSetChanged {
    param(
        [array]$Mappings,
        [hashtable]$Existing
    )

    if ($Mappings.Count -ne $Existing.Count) {
        return $true
    }
    foreach ($Mapping in $Mappings) {
        $DeviceId = [string]$Mapping.device_id
        if (-not $Existing.ContainsKey($DeviceId)) {
            return $true
        }
        $Before = $Existing[$DeviceId]
        if (
            [string]$Before.hostname -ne [string]$Mapping.hostname -or
            [string]$Before.loopback -ne [string]$Mapping.loopback -or
            [string]$Before.server_ipv4 -ne [string]$Mapping.server_ipv4 -or
            [int]$Before.rdp_port -ne [int]$Mapping.rdp_port
        ) {
            return $true
        }
    }
    return $false
}

function Write-NamedAccessState {
    param(
        [object]$Manifest,
        [array]$Mappings,
        [string]$RoutingMode
    )

    $MapForState = [ordered]@{}
    foreach ($Mapping in $Mappings) {
        $MapForState[[string]$Mapping.device_id] = [ordered]@{
            hostname = [string]$Mapping.hostname
            loopback = [string]$Mapping.loopback
            server_ipv4 = [string]$Mapping.server_ipv4
            rdp_port = [int]$Mapping.rdp_port
            enabled = [bool]$Mapping.enabled
        }
    }

    Write-SecureJsonFile -Path $StatePath -Value ([ordered]@{
        version = 2
        connector_id = [string]$Manifest.connector.id
        connector_name = [string]$Manifest.connector.name
        device_domain = [string]$Manifest.server.device_domain
        routing_mode = $RoutingMode
        updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        mappings = $MapForState
    })
}

function Remove-PortProxyRuntime {
    param([hashtable]$Existing)

    foreach ($Entry in $Existing.Values) {
        $Address = [string]$Entry.loopback
        if (Test-LoopbackAddress -Address $Address) {
            try {
                Remove-PortProxy -ListenAddress $Address
            }
            catch {
            }
        }
    }

    if (Test-Path -LiteralPath $HostsPath) {
        try {
            $Original = [IO.File]::ReadAllText($HostsPath)
            $Clean = Remove-ManagedHostsBlock -Text $Original
            if ($Clean -ne $Original) {
                [IO.File]::WriteAllText(
                    $HostsPath,
                    $Clean.TrimEnd([char]13, [char]10) + [Environment]::NewLine,
                    (New-Object Text.UTF8Encoding($false))
                )
                & $Ipconfig /flushdns | Out-Null
            }
        }
        catch {
        }
    }
}

function Invoke-NamedAccessSync {
    $Config = Read-JsonFile -Path $ConfigPath
    if (-not $Config) {
        throw "Named Access config is missing: $ConfigPath"
    }
    $Manifest = Get-Manifest -Config $Config
    $State = Read-JsonFile -Path $StatePath
    $Existing = Convert-StateMappings -State $State
    $Mappings = @(Build-Mappings -Manifest $Manifest -Existing $Existing)
    $RoutingMode = ([string]$Config.routing_mode).Trim().ToLowerInvariant()
    if ($RoutingMode -notin @('portproxy', 'launcher')) {
        throw "Unsupported Named Access routing mode: $RoutingMode"
    }

    $MappingsChanged = Test-MappingSetChanged -Mappings $Mappings -Existing $Existing
    $ModeChanged = ([string]$State.routing_mode) -ne $RoutingMode

    if ($RoutingMode -eq 'launcher') {
        if ([string]$State.routing_mode -eq 'portproxy') {
            Remove-PortProxyRuntime -Existing $Existing
        }
        if ($MappingsChanged -or $ModeChanged -or -not $State) {
            Write-NamedAccessState -Manifest $Manifest -Mappings $Mappings -RoutingMode $RoutingMode
            Write-Log (
                "SYNC=PASS mode=launcher connector=$($Manifest.connector.id) " +
                "devices=$($Mappings.Count)"
            )
        }
        else {
            Write-Log (
                "SYNC=UNCHANGED mode=launcher connector=$($Manifest.connector.id) " +
                "devices=$($Mappings.Count)"
            )
        }
        return
    }

    if (-not $MappingsChanged -and -not $ModeChanged) {
        Write-Log (
            "SYNC=UNCHANGED mode=portproxy connector=$($Manifest.connector.id) " +
            "devices=$($Mappings.Count)"
        )
        return
    }

    Start-IpHelper

    $Owned = New-Object 'System.Collections.Generic.HashSet[string]' (
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Entry in $Existing.Values) {
        $Address = [string]$Entry.loopback
        if (Test-LoopbackAddress -Address $Address) {
            [void]$Owned.Add($Address)
        }
    }
    foreach ($Mapping in $Mappings) {
        [void]$Owned.Add([string]$Mapping.loopback)
    }
    Assert-LocalRdpPortAvailable -OwnedAddresses $Owned

    $OriginalHosts = [IO.File]::ReadAllText($HostsPath)
    try {
        foreach ($Mapping in $Mappings) {
            $DeviceId = [string]$Mapping.device_id
            $NeedsProxyUpdate = $true
            if ($Existing.ContainsKey($DeviceId)) {
                $Before = $Existing[$DeviceId]
                $NeedsProxyUpdate = (
                    [string]$Before.loopback -ne [string]$Mapping.loopback -or
                    [string]$Before.server_ipv4 -ne [string]$Mapping.server_ipv4 -or
                    [int]$Before.rdp_port -ne [int]$Mapping.rdp_port
                )
            }
            if ($NeedsProxyUpdate) {
                Add-PortProxy `
                    -ListenAddress ([string]$Mapping.loopback) `
                    -ServerIPv4 ([string]$Mapping.server_ipv4) `
                    -RemotePort ([int]$Mapping.rdp_port)
            }
        }

        Write-ManagedHosts -OriginalText $OriginalHosts -Mappings $Mappings

        $CurrentAddresses = New-Object 'System.Collections.Generic.HashSet[string]' (
            [StringComparer]::OrdinalIgnoreCase
        )
        foreach ($Mapping in $Mappings) {
            [void]$CurrentAddresses.Add([string]$Mapping.loopback)
        }
        foreach ($Entry in $Existing.Values) {
            $OldAddress = [string]$Entry.loopback
            if (
                (Test-LoopbackAddress -Address $OldAddress) -and
                -not $CurrentAddresses.Contains($OldAddress)
            ) {
                Remove-PortProxy -ListenAddress $OldAddress
            }
        }

        Write-NamedAccessState -Manifest $Manifest -Mappings $Mappings -RoutingMode $RoutingMode

        Write-Log (
            "SYNC=PASS mode=portproxy connector=$($Manifest.connector.id) " +
            "devices=$($Mappings.Count)"
        )
    }
    catch {
        try {
            [IO.File]::WriteAllText(
                $HostsPath,
                $OriginalHosts,
                (New-Object Text.UTF8Encoding($false))
            )
            & $Ipconfig /flushdns | Out-Null
        }
        catch {
        }

        foreach ($Mapping in $Mappings) {
            try {
                Remove-PortProxy -ListenAddress ([string]$Mapping.loopback)
            }
            catch {
            }
        }
        foreach ($Entry in $Existing.Values) {
            $OldAddress = [string]$Entry.loopback
            if (-not (Test-LoopbackAddress -Address $OldAddress)) {
                continue
            }
            try {
                Add-PortProxy `
                    -ListenAddress $OldAddress `
                    -ServerIPv4 ([string]$Entry.server_ipv4) `
                    -RemotePort ([int]$Entry.rdp_port)
            }
            catch {
            }
        }
        throw
    }
}

New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
$Mutex = New-Object Threading.Mutex(
    $false,
    'Global\BakunityRdpNamedAccess'
)
$HasMutex = $false
try {
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        if ($Once) {
            Write-Host 'NAMED_ACCESS=ALREADY_RUNNING'
        }
        exit 0
    }

    do {
        try {
            Invoke-NamedAccessSync
            if ($Once) {
                Write-Host 'NAMED_ACCESS=PASS'
            }
        }
        catch {
            Write-Log "SYNC=ERROR $($_.Exception.Message)"
            if ($Once) {
                Write-Host "NAMED_ACCESS=ERROR:$($_.Exception.Message)"
                exit 1
            }
        }

        if ($Once) {
            break
        }
        Start-Sleep -Seconds $SyncIntervalSeconds
    } while ($true)
}
finally {
    if ($HasMutex) {
        try {
            $Mutex.ReleaseMutex()
        }
        catch {
        }
    }
    $Mutex.Dispose()
}
