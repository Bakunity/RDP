param(
    [string]$RepositoryRef = 'main',
    [string]$ExpectedDeviceId = ''
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$TaskName = 'Hermes RDP Agent'
$AgentPath = Join-Path $BaseDir 'HermesRdpAgent.ps1'
$ConfigPath = Join-Path $BaseDir 'device.json'
$StatePath = Join-Path $BaseDir 'agent-state.json'
$LogPath = Join-Path $BaseDir 'agent.log'
$StartupTimeoutSeconds = 75
$StartupStableSeconds = 20
$CandidatePath = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpRepair-$([Guid]::NewGuid().ToString('N')).ps1")

$PinnedHttpClientSource = @'
using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace HermesRdp
{
    public static class RepairPinnedHttpClientFactory
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
            client.Timeout = TimeSpan.FromSeconds(30);
            return client;
        }
    }
}
'@

if (-not ('HermesRdp.RepairPinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $PinnedHttpClientSource `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
}

function Get-Sha256 {
    param([string]$Path)

    return (
        Get-FileHash `
            -LiteralPath $Path `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}

function Set-SecretAcl {
    param([string]$Path)

    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Invoke-PinnedPost {
    param(
        [System.Net.Http.HttpClient]$Client,
        [string]$Url,
        [object]$Body,
        [string]$Token
    )

    $Json = $Body | ConvertTo-Json -Depth 8 -Compress
    $Request = New-Object System.Net.Http.HttpRequestMessage(
        [System.Net.Http.HttpMethod]::Post,
        $Url
    )
    $Request.Content = New-Object System.Net.Http.StringContent(
        $Json,
        [Text.Encoding]::UTF8,
        'application/json'
    )
    if ($Token) {
        $Request.Headers.Authorization =
            New-Object System.Net.Http.Headers.AuthenticationHeaderValue(
                'Bearer',
                $Token
            )
    }

    try {
        $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        try {
            $Text = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $Response.IsSuccessStatusCode) {
                throw "HTTP $([int]$Response.StatusCode): $Text"
            }
            if ([string]::IsNullOrWhiteSpace($Text)) {
                return $null
            }
            return $Text | ConvertFrom-Json
        }
        finally {
            $Response.Dispose()
        }
    }
    finally {
        $Request.Dispose()
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

function Ensure-OpenSshClient {
    $CanonicalSystem32 = Join-Path $env:WINDIR 'System32'
    $NativeSystem32 = $CanonicalSystem32
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        $NativeSystem32 = Join-Path $env:WINDIR 'Sysnative'
    }

    $CanonicalSsh = Join-Path $CanonicalSystem32 'OpenSSH\ssh.exe'
    $ProbeSsh = Join-Path $NativeSystem32 'OpenSSH\ssh.exe'
    $Keygen = Join-Path $NativeSystem32 'OpenSSH\ssh-keygen.exe'

    if (
        (Test-Path -LiteralPath $ProbeSsh) -and
        (Test-Path -LiteralPath $Keygen)
    ) {
        return @{
            ssh = $CanonicalSsh
            keygen = $Keygen
        }
    }

    $Capability = Get-WindowsCapability `
        -Online `
        -Name 'OpenSSH.Client*' |
        Select-Object -First 1

    if (-not $Capability) {
        throw 'Компонент OpenSSH Client не найден в Windows.'
    }
    if ($Capability.State -ne 'Installed') {
        Write-Host 'Восстанавливаю стандартный OpenSSH Client Windows...'
        $InstallResult = Add-WindowsCapability `
            -Online `
            -Name $Capability.Name
        if ($InstallResult.RestartNeeded) {
            throw 'OpenSSH установлен, но Windows требует перезагрузку перед repair.'
        }
    }

    if (
        -not (Test-Path -LiteralPath $ProbeSsh) -or
        -not (Test-Path -LiteralPath $Keygen)
    ) {
        throw 'OpenSSH Client установлен, но native ssh.exe/ssh-keygen.exe не найдены.'
    }

    return @{
        ssh = $CanonicalSsh
        keygen = $Keygen
    }
}

function Get-HermesAgentProcesses {
    return @(
        Get-CimInstance `
            Win32_Process `
            -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($AgentPath)
        }
    )
}

function Get-HermesSshProcesses {
    param([string]$KeyPath)

    return @(
        Get-CimInstance `
            Win32_Process `
            -Filter "Name='ssh.exe'" `
            -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($KeyPath)
        }
    )
}

function Stop-HermesRuntime {
    param([string]$KeyPath)

    $Processes = @(
        @(Get-HermesAgentProcesses) +
        @(Get-HermesSshProcesses -KeyPath $KeyPath)
    ) |
        Sort-Object ProcessId -Unique

    foreach ($Process in $Processes) {
        Stop-Process `
            -Id ([int]$Process.ProcessId) `
            -Force `
            -ErrorAction SilentlyContinue
    }
}

function Get-AgentLogLineCount {
    if (-not (Test-Path -LiteralPath $LogPath)) {
        return 0
    }
    return @(Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue).Count
}

function Get-NewControlErrors {
    param([int]$StartLine)

    if (-not (Test-Path -LiteralPath $LogPath)) {
        return @()
    }
    $Lines = @(Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue)
    if ($StartLine -ge $Lines.Count) {
        return @()
    }
    return @(
        $Lines[$StartLine..($Lines.Count - 1)] |
        Where-Object { $_ -match 'Control poll error:' }
    )
}

function Wait-HermesRuntimeReady {
    param(
        [string]$KeyPath,
        [bool]$DesiredEnabled,
        [int]$LogStartLine,
        [int]$TimeoutSeconds,
        [int]$StableSeconds
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $StableSince = $null
    $StableAgentPid = 0
    $StableSshPid = -1

    while ([DateTime]::UtcNow -lt $Deadline) {
        $Task = Get-ScheduledTask `
            -TaskName $TaskName `
            -ErrorAction SilentlyContinue
        $Agents = @(Get-HermesAgentProcesses)
        $Ssh = @(Get-HermesSshProcesses -KeyPath $KeyPath)
        $ExpectedSshCount = if ($DesiredEnabled) { 1 } else { 0 }

        $RuntimeShapeOk = (
            $Task -and
            $Task.State -eq 'Running' -and
            $Agents.Count -eq 1 -and
            $Ssh.Count -eq $ExpectedSshCount
        )

        if ($RuntimeShapeOk) {
            $AgentPid = [int]$Agents[0].ProcessId
            $SshPid = if ($Ssh.Count -eq 1) {
                [int]$Ssh[0].ProcessId
            }
            else {
                0
            }

            if (
                $StableAgentPid -ne $AgentPid -or
                $StableSshPid -ne $SshPid
            ) {
                $StableAgentPid = $AgentPid
                $StableSshPid = $SshPid
                $StableSince = [DateTime]::UtcNow
            }
            elseif (
                $StableSince -and
                (([DateTime]::UtcNow - $StableSince).TotalSeconds -ge $StableSeconds)
            ) {
                $ControlErrors = @(Get-NewControlErrors -StartLine $LogStartLine)
                if ($ControlErrors.Count -gt 0) {
                    throw (
                        'После repair агент не проходит control-plane запросы: ' +
                        [string]$ControlErrors[-1]
                    )
                }
                return @{
                    AgentPid = $AgentPid
                    SshPid = $SshPid
                    SshCount = $Ssh.Count
                }
            }
        }
        else {
            $StableSince = $null
            $StableAgentPid = 0
            $StableSshPid = -1
        }

        Start-Sleep -Seconds 1
    }

    $ControlErrors = @(Get-NewControlErrors -StartLine $LogStartLine)
    $Detail = if ($ControlErrors.Count -gt 0) {
        [string]$ControlErrors[-1]
    }
    else {
        'нет новых control-plane ошибок в agent.log'
    }
    throw (
        "Hermes repair не вышел в стабильное состояние за $TimeoutSeconds сек. $Detail"
    )
}

function Register-CanonicalTask {
    $Action = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument (
            '-NoProfile -ExecutionPolicy Bypass -File ' +
            "`"$AgentPath`""
        )
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Trigger.Delay = 'PT20S'
    $Principal = New-ScheduledTaskPrincipal `
        -UserId 'SYSTEM' `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $Settings `
        -Force |
        Out-Null
}

Write-Host '=== HERMES RDP REPAIR ===' -ForegroundColor Cyan

if ([Environment]::Is64BitOperatingSystem -ne $true) {
    throw 'Поддерживается только 64-битная Windows.'
}
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw (
        'device.json отсутствует. Repair не создаёт новую identity. ' +
        'Нужен отдельный owner-authorized recovery flow.'
    )
}

try {
    $Config = Get-Content `
        -LiteralPath $ConfigPath `
        -Raw |
        ConvertFrom-Json
}
catch {
    throw (
        'device.json повреждён. Repair не выполняет fresh pairing и не ' +
        'перезаписывает identity автоматически.'
    )
}

$DeviceId = [string]$Config.device_id
$DeviceToken = [string]$Config.device_token
$KeyPath = [string]$Config.ssh_key_path
$KnownHostsPath = [string]$Config.known_hosts_path
$ApiBase = [string]$Config.api_base_url
$ExpectedFingerprint = (
    [string]$Config.api_fingerprint -replace '[^0-9A-Fa-f]', ''
).ToUpperInvariant()

if ([string]::IsNullOrWhiteSpace($DeviceId)) {
    throw 'В device.json отсутствует device_id.'
}
if (
    -not [string]::IsNullOrWhiteSpace($ExpectedDeviceId) -and
    $DeviceId -ne $ExpectedDeviceId
) {
    throw (
        "Эта команда предназначена для другого Hermes-устройства. " +
        "Локальный DeviceId=$DeviceId"
    )
}
if ([string]::IsNullOrWhiteSpace($DeviceToken)) {
    throw 'В device.json отсутствует device_token; нужен owner-authorized recovery.'
}
if ([string]::IsNullOrWhiteSpace($ApiBase)) {
    throw 'В device.json отсутствует api_base_url.'
}
if ($ExpectedFingerprint.Length -ne 64) {
    throw 'В device.json отсутствует корректный SHA-256 fingerprint API.'
}
if ([string]::IsNullOrWhiteSpace($KeyPath)) {
    throw 'В device.json отсутствует ssh_key_path.'
}
if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw (
        'Приватный SSH-ключ Hermes отсутствует. Repair не генерирует новый ' +
        'ключ без server-authorized rekey flow.'
    )
}
$PublicKeyPath = "$KeyPath.pub"
if (-not (Test-Path -LiteralPath $PublicKeyPath)) {
    throw 'Публичный SSH-ключ Hermes отсутствует.'
}
if (
    [string]::IsNullOrWhiteSpace($KnownHostsPath) -or
    -not (Test-Path -LiteralPath $KnownHostsPath)
) {
    throw (
        'known_hosts Hermes отсутствует. Текущий repair не заменяет SSH trust ' +
        'anchor без отдельного server-authenticated recovery endpoint.'
    )
}

$OpenSsh = Ensure-OpenSshClient
$CanonicalSshPath = [string]$OpenSsh.ssh
$KeygenPath = [string]$OpenSsh.keygen

$DerivedPublicKey = (
    & $KeygenPath -y -f $KeyPath 2>$null |
    Select-Object -First 1
).Trim()
$StoredPublicParts = (
    Get-Content -LiteralPath $PublicKeyPath -Raw
).Trim().Split(
    [char[]]" `t",
    [StringSplitOptions]::RemoveEmptyEntries
)
$DerivedPublicParts = $DerivedPublicKey.Split(
    [char[]]" `t",
    [StringSplitOptions]::RemoveEmptyEntries
)
if (
    $StoredPublicParts.Count -lt 2 -or
    $DerivedPublicParts.Count -lt 2 -or
    $StoredPublicParts[0] -ne 'ssh-ed25519' -or
    $DerivedPublicParts[0] -ne 'ssh-ed25519' -or
    $StoredPublicParts[1] -ne $DerivedPublicParts[1]
) {
    throw 'Локальные Ed25519 private/public key не соответствуют друг другу.'
}

$IdentityHashes = [ordered]@{
    config = Get-Sha256 -Path $ConfigPath
    private_key = Get-Sha256 -Path $KeyPath
    public_key = Get-Sha256 -Path $PublicKeyPath
    known_hosts = Get-Sha256 -Path $KnownHostsPath
}
$OriginalRdpPort = [int]$Config.rdp_port

$Http = [HermesRdp.RepairPinnedHttpClientFactory]::Create(
    $ExpectedFingerprint
)

try {
    $Health = $Http.GetStringAsync(
        "$ApiBase/healthz"
    ).GetAwaiter().GetResult() | ConvertFrom-Json

    if (
        (
            [string]$Health.fingerprint -replace '[^0-9A-Fa-f]', ''
        ).ToUpperInvariant() -ne $ExpectedFingerprint
    ) {
        throw 'Fingerprint в ответе /healthz не совпал с локальным trust anchor.'
    }
    if ([string]$Health.tunnel -ne 'openssh') {
        throw 'Сервер не сообщает Hermes OpenSSH transport.'
    }

    $ExistingSsh = @(Get-HermesSshProcesses -KeyPath $KeyPath)
    $LocalEnabled = $true
    if (Test-Path -LiteralPath $StatePath) {
        try {
            $LocalState = Get-Content `
                -LiteralPath $StatePath `
                -Raw |
                ConvertFrom-Json
            if ($LocalState.PSObject.Properties['enabled']) {
                $LocalEnabled = [bool]$LocalState.enabled
            }
        }
        catch {
        }
    }

    $Probe = Invoke-PinnedPost `
        -Client $Http `
        -Url "$ApiBase/v1/devices/$DeviceId/telemetry" `
        -Token $DeviceToken `
        -Body @{
            telemetry = @{
                repair_probe = $true
                access_enabled = [bool]$LocalEnabled
                ssh_tunnel_running = [bool]($ExistingSsh.Count -eq 1)
                ssh_process_count = [int]$ExistingSsh.Count
            }
        }

    if (-not $Probe -or -not $Probe.PSObject.Properties['desired_enabled']) {
        throw 'Repair auth probe не вернул desired_enabled.'
    }
    $DesiredEnabled = [bool]$Probe.desired_enabled

    $ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
    $CandidateUrl = (
        "https://raw.githubusercontent.com/$Repo/" +
        "$ResolvedSha/client/HermesRdpAgent.ps1"
    )
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CandidateUrl `
        -OutFile $CandidatePath

    $Tokens = $null
    $ParseErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $CandidatePath,
        [ref]$Tokens,
        [ref]$ParseErrors
    )
    if ($ParseErrors.Count -gt 0) {
        throw "Candidate parse error: $($ParseErrors[0].Message)"
    }

    $TaskBefore = Get-ScheduledTask `
        -TaskName $TaskName `
        -ErrorAction SilentlyContinue
    $TaskExistedBefore = $null -ne $TaskBefore
    $TaskStateBefore = if ($TaskBefore) {
        [string]$TaskBefore.State
    }
    else {
        'ABSENT'
    }
    $TaskXmlBefore = if ($TaskBefore) {
        Export-ScheduledTask -TaskName $TaskName
    }
    else {
        $null
    }
    $AgentExistedBefore = Test-Path -LiteralPath $AgentPath

    $BackupRoot = Join-Path $BaseDir 'backups\repairs'
    $BackupDir = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    New-Item `
        -ItemType Directory `
        -Path $BackupDir `
        -Force |
        Out-Null

    $BackupAgent = Join-Path $BackupDir 'HermesRdpAgent.ps1'
    $BackupTask = Join-Path $BackupDir 'scheduled-task.xml'
    $BackupMetadata = Join-Path $BackupDir 'repair-metadata.json'

    if ($AgentExistedBefore) {
        Copy-Item `
            -LiteralPath $AgentPath `
            -Destination $BackupAgent `
            -Force
    }
    if ($TaskExistedBefore) {
        $TaskXmlBefore |
            Set-Content `
                -LiteralPath $BackupTask `
                -Encoding UTF8
    }

    [ordered]@{
        device_id = $DeviceId
        rdp_port = $OriginalRdpPort
        requested_ref = $RepositoryRef
        resolved_sha = $ResolvedSha
        task_existed_before = [bool]$TaskExistedBefore
        task_state_before = $TaskStateBefore
        agent_existed_before = [bool]$AgentExistedBefore
        config_sha256 = $IdentityHashes.config
        private_key_sha256 = $IdentityHashes.private_key
        public_key_sha256 = $IdentityHashes.public_key
        known_hosts_sha256 = $IdentityHashes.known_hosts
        candidate_agent_sha256 = Get-Sha256 -Path $CandidatePath
        desired_enabled = [bool]$DesiredEnabled
    } |
        ConvertTo-Json -Depth 4 |
        Set-Content `
            -LiteralPath $BackupMetadata `
            -Encoding UTF8

    try {
        Stop-ScheduledTask `
            -TaskName $TaskName `
            -ErrorAction SilentlyContinue
        Stop-HermesRuntime -KeyPath $KeyPath

        Copy-Item `
            -LiteralPath $CandidatePath `
            -Destination $AgentPath `
            -Force

        $ActiveTokens = $null
        $ActiveParseErrors = $null
        [void][Management.Automation.Language.Parser]::ParseFile(
            $AgentPath,
            [ref]$ActiveTokens,
            [ref]$ActiveParseErrors
        )
        if ($ActiveParseErrors.Count -gt 0) {
            throw "Activated agent parse error: $($ActiveParseErrors[0].Message)"
        }

        # Repair intentionally rebuilds only local runtime scaffolding. It never
        # creates a new device, token, SSH identity or RDP port.
        Register-CanonicalTask

        foreach ($Secret in @(
            $ConfigPath,
            $KeyPath,
            $KnownHostsPath
        )) {
            Set-SecretAcl -Path $Secret
        }

        Set-ItemProperty `
            -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' `
            -Name fDenyTSConnections `
            -Value 0
        Get-NetFirewallRule `
            -Name 'RemoteDesktop-*' `
            -ErrorAction SilentlyContinue |
            Enable-NetFirewallRule
        Set-Service -Name TermService -StartupType Automatic
        Start-Service -Name TermService

        # Preserve the canonical native path expected by the SYSTEM task. If a
        # historical config contains the same canonical path, no config write
        # occurs; repair deliberately refuses to rewrite identity/config data.
        if (
            -not [string]::IsNullOrWhiteSpace([string]$Config.ssh_path) -and
            [string]$Config.ssh_path -ne $CanonicalSshPath
        ) {
            throw (
                'ssh_path в device.json отличается от canonical Windows ' +
                'OpenSSH path; automatic config rewrite is intentionally blocked.'
            )
        }

        $LogStartLine = Get-AgentLogLineCount
        Start-ScheduledTask -TaskName $TaskName
        $Ready = Wait-HermesRuntimeReady `
            -KeyPath $KeyPath `
            -DesiredEnabled $DesiredEnabled `
            -LogStartLine $LogStartLine `
            -TimeoutSeconds $StartupTimeoutSeconds `
            -StableSeconds $StartupStableSeconds

        $ConfigAfter = Get-Content `
            -LiteralPath $ConfigPath `
            -Raw |
            ConvertFrom-Json
        $IdentityOk = (
            (Get-Sha256 -Path $ConfigPath) -eq $IdentityHashes.config -and
            (Get-Sha256 -Path $KeyPath) -eq $IdentityHashes.private_key -and
            (Get-Sha256 -Path $PublicKeyPath) -eq $IdentityHashes.public_key -and
            (Get-Sha256 -Path $KnownHostsPath) -eq $IdentityHashes.known_hosts -and
            [string]$ConfigAfter.device_id -eq $DeviceId -and
            [int]$ConfigAfter.rdp_port -eq $OriginalRdpPort
        )
        if (-not $IdentityOk) {
            throw 'Repair изменил защищённую identity/config boundary.'
        }

        Write-Host
        Write-Host 'REPAIR=PASS' -ForegroundColor Green
        Write-Host "ResolvedRef: $ResolvedSha"
        Write-Host "Backup: $BackupDir"
        Write-Host "DeviceId: $DeviceId"
        Write-Host "RdpPort: $OriginalRdpPort"
        Write-Host "DesiredAccess: $DesiredEnabled"
        Write-Host "AgentPID: $($Ready.AgentPid)"
        Write-Host "HermesSshCount: $($Ready.SshCount)"
    }
    catch {
        $RepairFailure = $_
        $RollbackOk = $true
        $RollbackDetail = ''

        try {
            Stop-ScheduledTask `
                -TaskName $TaskName `
                -ErrorAction SilentlyContinue
            Stop-HermesRuntime -KeyPath $KeyPath

            if ($AgentExistedBefore) {
                Copy-Item `
                    -LiteralPath $BackupAgent `
                    -Destination $AgentPath `
                    -Force
            }
            else {
                Remove-Item `
                    -LiteralPath $AgentPath `
                    -Force `
                    -ErrorAction SilentlyContinue
            }

            if ($TaskExistedBefore) {
                Register-ScheduledTask `
                    -TaskName $TaskName `
                    -Xml $TaskXmlBefore `
                    -Force |
                    Out-Null

                if ($TaskStateBefore -eq 'Disabled') {
                    Disable-ScheduledTask `
                        -TaskName $TaskName `
                        -ErrorAction SilentlyContinue |
                        Out-Null
                }
                elseif ($TaskStateBefore -eq 'Running') {
                    Start-ScheduledTask -TaskName $TaskName
                }
                else {
                    Stop-ScheduledTask `
                        -TaskName $TaskName `
                        -ErrorAction SilentlyContinue
                }
            }
            else {
                Unregister-ScheduledTask `
                    -TaskName $TaskName `
                    -Confirm:$false `
                    -ErrorAction SilentlyContinue
            }

            $IdentityRestored = (
                (Get-Sha256 -Path $ConfigPath) -eq $IdentityHashes.config -and
                (Get-Sha256 -Path $KeyPath) -eq $IdentityHashes.private_key -and
                (Get-Sha256 -Path $PublicKeyPath) -eq $IdentityHashes.public_key -and
                (Get-Sha256 -Path $KnownHostsPath) -eq $IdentityHashes.known_hosts
            )
            if (-not $IdentityRestored) {
                throw 'Identity hash changed during repair rollback.'
            }
        }
        catch {
            $RollbackOk = $false
            $RollbackDetail = $_.Exception.Message
        }

        if ($RollbackOk) {
            Write-Host 'ROLLBACK=PASS' -ForegroundColor Yellow
            Write-Host "Backup: $BackupDir"
            throw (
                'Repair не применён; предыдущая локальная runtime-схема ' +
                "восстановлена. Причина: $($RepairFailure.Exception.Message)"
            )
        }

        Write-Host 'ROLLBACK=FAIL' -ForegroundColor Red
        Write-Host "Backup: $BackupDir"
        throw (
            'Repair и автоматический rollback завершились ошибкой. ' +
            "Repair: $($RepairFailure.Exception.Message) " +
            "Rollback: $RollbackDetail"
        )
    }
}
finally {
    if ($Http) {
        $Http.Dispose()
    }
    Remove-Item `
        -LiteralPath $CandidatePath `
        -Force `
        -ErrorAction SilentlyContinue
}
