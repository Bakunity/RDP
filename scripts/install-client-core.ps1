param(
    [Parameter(Mandatory = $true)]
    [string]$Server,

    [Parameter(Mandatory = $true)]
    [string]$PairCode,

    [Parameter(Mandatory = $true)]
    [string]$Fingerprint,

    [string]$Name,
    [int]$ApiPort = 7443,
    [string]$RepositoryRef = 'main'
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Net.Http

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$TaskName = 'Hermes RDP Agent'
$ApiBase = "https://${Server}:${ApiPort}"
$StartupTimeoutSeconds = 75
$StartupStableSeconds = 20
$AgentCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpInstallAgent-$([Guid]::NewGuid().ToString('N')).ps1")
$CertSetupCandidate = Join-Path (
    [IO.Path]::GetTempPath()
) ("HermesRdpInstallCertSetup-$([Guid]::NewGuid().ToString('N')).ps1")
$ExpectedFingerprint = (
    $Fingerprint -replace '[^0-9A-Fa-f]', ''
).ToUpperInvariant()

$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    $CurrentIdentity
)
if (-not $CurrentPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
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

        public static bool ValidateCertificate(
            X509Certificate2 certificate,
            string expectedFingerprint)
        {
            string expected = NormalizeFingerprint(expectedFingerprint);
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
                return ValidateCertificate(certificate, expected);
            };
            var client = new HttpClient(handler);
            client.Timeout = TimeSpan.FromSeconds(30);
            return client;
        }
    }
}
'@

if (-not ('HermesRdp.PinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $PinnedHttpClientSource `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
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

function Set-SecretAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
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

function Get-NativePowerShellPath {
    $System32 = Join-Path $env:WINDIR 'System32'
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return Join-Path $System32 'WindowsPowerShell\v1.0\powershell.exe'
}

function Invoke-CertificateRotationSetup {
    param(
        [string]$SetupPath,
        [string]$ResolvedSha
    )

    $NativePowerShell = Get-NativePowerShellPath
    & $NativePowerShell `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $SetupPath `
        -RepositoryRef $ResolvedSha
    if ($LASTEXITCODE -ne 0) {
        throw "Certificate rotation setup failed with code $LASTEXITCODE"
    }
}

function Stop-HermesProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq 'frpc.exe') -or
            ($_.Name -eq 'ssh.exe' -and $_.CommandLine -and
                $_.CommandLine.Contains('HermesRDP')) -or
            ($_.CommandLine -and
                $_.CommandLine.Contains('HermesRdpAgent.ps1'))
        } |
        ForEach-Object {
            Stop-Process `
                -Id $_.ProcessId `
                -Force `
                -ErrorAction SilentlyContinue
        }
}

function Get-HermesSshProcess {
    param([string]$KeyPath)

    return Get-CimInstance `
        Win32_Process `
        -Filter "Name='ssh.exe'" `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($KeyPath)
        } |
        Select-Object -First 1
}

function Get-StartupDetail {
    $Sections = @()
    foreach ($Item in @(
        @{ Name = 'agent.log'; Path = (Join-Path $BaseDir 'agent.log') },
        @{ Name = 'ssh-error.log'; Path = (Join-Path $BaseDir 'ssh-error.log') }
    )) {
        if (Test-Path -LiteralPath $Item.Path) {
            $Tail = (
                Get-Content -LiteralPath $Item.Path -Tail 20 |
                    Out-String
            ).Trim()
            if ($Tail) {
                $Sections += "$($Item.Name):`n$Tail"
            }
        }
    }
    if ($Sections.Count -eq 0) {
        return 'agent.log/ssh-error.log ещё не созданы'
    }
    return ($Sections -join "`n")
}

function Wait-HermesTunnelReady {
    param(
        [string]$KeyPath,
        [int]$TimeoutSeconds,
        [int]$StableSeconds
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $StableSince = $null
    $StablePid = 0

    while ([DateTime]::UtcNow -lt $Deadline) {
        $Process = Get-HermesSshProcess -KeyPath $KeyPath
        if ($Process) {
            $PidValue = [int]$Process.ProcessId
            if ($StablePid -ne $PidValue) {
                $StablePid = $PidValue
                $StableSince = [DateTime]::UtcNow
            }
            elseif (
                $StableSince -and
                (([DateTime]::UtcNow - $StableSince).TotalSeconds -ge $StableSeconds)
            ) {
                return $Process
            }
        }
        else {
            $StablePid = 0
            $StableSince = $null
        }
        Start-Sleep -Seconds 1
    }

    $Detail = Get-StartupDetail
    throw (
        "SSH-туннель не вышел в стабильное состояние за " +
        "$TimeoutSeconds сек. $Detail"
    )
}

function Restore-InstallSnapshot {
    param(
        [string]$BasePath,
        [string]$SnapshotPath,
        [bool]$BaseExistedBefore,
        [bool]$BackupRootExistedBefore
    )

    if (-not $BaseExistedBefore) {
        Remove-Item `
            -LiteralPath $BasePath `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
        return
    }

    Get-ChildItem `
        -LiteralPath $BasePath `
        -Force `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'backups' } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    if (Test-Path -LiteralPath $SnapshotPath) {
        Get-ChildItem `
            -LiteralPath $SnapshotPath `
            -Force `
            -ErrorAction SilentlyContinue |
            Copy-Item `
                -Destination $BasePath `
                -Recurse `
                -Force
        Remove-Item `
            -LiteralPath $SnapshotPath `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
    }

    $BackupRoot = Join-Path $BasePath 'backups'
    if (
        -not $BackupRootExistedBefore -and
        (Test-Path -LiteralPath $BackupRoot)
    ) {
        $Remaining = @(
            Get-ChildItem `
                -LiteralPath $BackupRoot `
                -Force `
                -ErrorAction SilentlyContinue
        )
        if ($Remaining.Count -eq 0) {
            Remove-Item `
                -LiteralPath $BackupRoot `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-OpenSshClient {
    $CanonicalSystem32 = Join-Path $env:WINDIR 'System32'
    $NativeSystem32 = $CanonicalSystem32
    if (
        [Environment]::Is64BitOperatingSystem -and
        -not [Environment]::Is64BitProcess
    ) {
        # A 32-bit PowerShell process is redirected away from real x64
        # System32. Sysnative is the supported alias to reach native tools.
        $NativeSystem32 = Join-Path $env:WINDIR 'Sysnative'
    }

    $SshPath = Join-Path $CanonicalSystem32 'OpenSSH\ssh.exe'
    $ProbeSshPath = Join-Path $NativeSystem32 'OpenSSH\ssh.exe'
    $KeygenPath = Join-Path $NativeSystem32 'OpenSSH\ssh-keygen.exe'

    if (
        (Test-Path -LiteralPath $ProbeSshPath) -and
        (Test-Path -LiteralPath $KeygenPath)
    ) {
        return @{
            # Keep the canonical path in device.json. Scheduled Task runs in
            # the native environment where Sysnative is not a real directory.
            ssh = $SshPath
            keygen = $KeygenPath
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
        Write-Host 'Устанавливаю стандартный OpenSSH Client Windows...'
        $InstallResult = Add-WindowsCapability `
            -Online `
            -Name $Capability.Name
        if ($InstallResult.RestartNeeded) {
            Write-Host 'Windows сообщает, что для OpenSSH требуется перезагрузка.'
        }
    }

    if (
        -not (Test-Path -LiteralPath $ProbeSshPath) -or
        -not (Test-Path -LiteralPath $KeygenPath)
    ) {
        throw (
            'OpenSSH Client отмечен как установлен, но системные ' +
            'ssh.exe/ssh-keygen.exe не найдены.'
        )
    }

    return @{
        ssh = $SshPath
        keygen = $KeygenPath
    }
}

Write-Host '=== HERMES RDP OPENSSH INSTALLER ===' -ForegroundColor Cyan

if ([Environment]::Is64BitOperatingSystem -ne $true) {
    throw 'Поддерживается только 64-битная Windows.'
}

$Os = Get-CimInstance Win32_OperatingSystem
$IsClientWindows = [int]$Os.ProductType -eq 1
$IsServerWindows = [int]$Os.ProductType -in @(2, 3)
if (-not ($IsClientWindows -or $IsServerWindows)) {
    throw "Неподдерживаемый тип Windows: ProductType=$($Os.ProductType)."
}
if (
    $IsClientWindows -and
    $Os.Caption -notmatch 'Pro|Enterprise|Education'
) {
    throw "Редакция '$($Os.Caption)' не поддерживает входящие RDP-подключения."
}
if (
    $IsServerWindows -and
    $Os.Caption -notmatch 'Windows Server'
) {
    throw "Серверная редакция '$($Os.Caption)' не распознана как Windows Server."
}

# "Добавить ПК" is a fresh-pairing flow. Never stop a working Hermes client
# when its durable local identity is already present. Repair/update is a
# separate operation and must preserve the existing server registration.
$ExistingConfigPath = Join-Path $BaseDir 'device.json'
$ExistingPrivateKeyPath = Join-Path $BaseDir 'id_ed25519'
$ExistingPublicKeyPath = "$ExistingPrivateKeyPath.pub"
if (
    (Test-Path -LiteralPath $ExistingConfigPath) -and
    (Test-Path -LiteralPath $ExistingPrivateKeyPath) -and
    (Test-Path -LiteralPath $ExistingPublicKeyPath)
) {
    try {
        $ExistingConfig = Get-Content `
            -LiteralPath $ExistingConfigPath `
            -Raw |
            ConvertFrom-Json
    }
    catch {
        $ExistingConfig = $null
    }
    if (
        $ExistingConfig -and
        -not [string]::IsNullOrWhiteSpace([string]$ExistingConfig.device_id) -and
        [int]$ExistingConfig.rdp_port -gt 0 -and
        -not [string]::IsNullOrWhiteSpace([string]$ExistingConfig.ssh_key_path)
    ) {
        throw (
            "Hermes RDP уже установлен на этом ПК (RDP-порт " +
            "$($ExistingConfig.rdp_port)). Команда 'Добавить ПК' ничего " +
            'не изменила. Для восстановления или обновления используйте ' +
            'отдельный repair/update flow.'
        )
    }
}

if (-not $Name) {
    $Name = Read-Host 'Название компьютера в Telegram'
}
if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = $env:COMPUTERNAME
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$AgentUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/client/HermesRdpAgent.ps1"
)
$CertSetupUrl = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/scripts/setup-client-cert-rotation.ps1"
)
try {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $AgentUrl `
        -OutFile $AgentCandidate
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $CertSetupUrl `
        -OutFile $CertSetupCandidate
    Assert-PowerShellFile -Path $AgentCandidate
    Assert-PowerShellFile -Path $CertSetupCandidate
}
catch {
    Remove-Item `
        -LiteralPath $AgentCandidate, $CertSetupCandidate `
        -Force `
        -ErrorAction SilentlyContinue
    throw
}

$OpenSsh = Ensure-OpenSshClient
$SshPath = [string]$OpenSsh.ssh
$KeygenPath = [string]$OpenSsh.keygen

$LegacyTasks = @(
    'Hermes FRPC Client'
    'Hermes Windows Monitor'
    'Hermes RDP Telegram Bot'
    $TaskName
)
foreach ($LegacyTask in $LegacyTasks) {
    Stop-ScheduledTask `
        -TaskName $LegacyTask `
        -ErrorAction SilentlyContinue
    if ($LegacyTask -ne $TaskName) {
        Unregister-ScheduledTask `
            -TaskName $LegacyTask `
            -Confirm:$false `
            -ErrorAction SilentlyContinue
    }
}
Stop-HermesProcesses

$BaseDirExistedBefore = Test-Path -LiteralPath $BaseDir
$BackupRoot = Join-Path $BaseDir 'backups'
$BackupRootExistedBefore = Test-Path -LiteralPath $BackupRoot
$BackupDir = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
if ($BaseDirExistedBefore) {
    New-Item `
        -ItemType Directory `
        -Path $BackupDir `
        -Force |
        Out-Null
    Get-ChildItem `
        -LiteralPath $BaseDir `
        -Force `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'backups' } |
        Copy-Item `
            -Destination $BackupDir `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null

$AgentPath = Join-Path $BaseDir 'HermesRdpAgent.ps1'
Copy-Item `
    -LiteralPath $AgentCandidate `
    -Destination $AgentPath `
    -Force
Assert-PowerShellFile -Path $AgentPath

$SshKeyPath = Join-Path $BaseDir 'id_ed25519'
$SshPublicKeyPath = "$SshKeyPath.pub"
if (
    -not (Test-Path -LiteralPath $SshKeyPath) -or
    -not (Test-Path -LiteralPath $SshPublicKeyPath)
) {
    Remove-Item `
        -LiteralPath $SshKeyPath, $SshPublicKeyPath `
        -Force `
        -ErrorAction SilentlyContinue
    $KeygenProcess = Start-Process `
        -FilePath $KeygenPath `
        -ArgumentList @(
            '-q'
            '-t'
            'ed25519'
            '-N'
            '""'
            '-C'
            "hermes-rdp-$env:COMPUTERNAME"
            '-f'
            $SshKeyPath
        ) `
        -Wait `
        -NoNewWindow `
        -PassThru
    if ($KeygenProcess.ExitCode -ne 0) {
        throw "ssh-keygen завершился с кодом $($KeygenProcess.ExitCode)"
    }
}

$PublicKeyParts = (
    Get-Content -LiteralPath $SshPublicKeyPath -Raw
).Trim().Split(
    [char[]]" `t",
    [StringSplitOptions]::RemoveEmptyEntries
)
if ($PublicKeyParts.Count -lt 2 -or $PublicKeyParts[0] -ne 'ssh-ed25519') {
    throw 'Сгенерирован некорректный SSH Ed25519 public key.'
}
$PublicKey = "$($PublicKeyParts[0]) $($PublicKeyParts[1])"
$MachineFingerprint = (Get-CimInstance Win32_ComputerSystemProduct).UUID

$Http = [HermesRdp.PinnedHttpClientFactory]::Create(
    $ExpectedFingerprint
)
$Pair = $null
$PairRequestStarted = $false
try {
    $Health = $Http.GetStringAsync(
        "$ApiBase/healthz"
    ).GetAwaiter().GetResult() | ConvertFrom-Json

    if (
        (
            $Health.fingerprint -replace '[^0-9A-Fa-f]', ''
        ).ToUpperInvariant() -ne $ExpectedFingerprint
    ) {
        throw 'Fingerprint в ответе сервера не совпал.'
    }
    if ([string]$Health.tunnel -ne 'openssh') {
        throw 'Сервер ещё не переведён на Hermes RDP OpenSSH.'
    }

    $PairRequestStarted = $true
    $Pair = Invoke-PinnedPost `
        -Client $Http `
        -Url "$ApiBase/v1/pair" `
        -Body @{
            code = $PairCode.ToUpperInvariant()
            display_name = $Name
            machine_name = $env:COMPUTERNAME
            fingerprint = $MachineFingerprint
            ssh_public_key = $PublicKey
        }

    $KnownHostsPath = Join-Path $BaseDir 'known_hosts'
    $KnownHostLine = (
        "[$Server]:$($Pair.ssh.port) " +
        [string]$Pair.ssh.host_key
    )
    [IO.File]::WriteAllText(
        $KnownHostsPath,
        "$KnownHostLine`n",
        [Text.UTF8Encoding]::new($false)
    )

    $Config = [ordered]@{
        device_id = [string]$Pair.device.id
        device_name = [string]$Pair.device.name
        device_token = [string]$Pair.device.token
        server = $Server
        api_base_url = $ApiBase
        api_fingerprint = $ExpectedFingerprint
        rdp_port = [int]$Pair.device.rdp_port
        ssh_path = $SshPath
        ssh_port = [int]$Pair.ssh.port
        ssh_user = [string]$Pair.ssh.user
        ssh_key_path = $SshKeyPath
        known_hosts_path = $KnownHostsPath
    }

    $ConfigPath = Join-Path $BaseDir 'device.json'
    $Config |
        ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $ConfigPath -Encoding UTF8

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

    foreach ($Secret in @(
        $ConfigPath,
        $SshKeyPath,
        $KnownHostsPath
    )) {
        Set-SecretAcl -Path $Secret
    }

    Remove-Item `
        -LiteralPath (
            Join-Path $BaseDir 'frpc.exe'
        ), (
            Join-Path $BaseDir 'frpc.toml'
        ), (
            Join-Path $BaseDir 'frp-ca.crt'
        ) `
        -Force `
        -ErrorAction SilentlyContinue

    Start-ScheduledTask -TaskName $TaskName
    $TunnelProcess = Wait-HermesTunnelReady `
        -KeyPath $SshKeyPath `
        -TimeoutSeconds $StartupTimeoutSeconds `
        -StableSeconds $StartupStableSeconds

    Invoke-CertificateRotationSetup `
        -SetupPath $CertSetupCandidate `
        -ResolvedSha $ResolvedSha

    Write-Host
    Write-Host '=== ГОТОВО ===' -ForegroundColor Green
    Write-Host "Компьютер: $($Pair.device.name)"
    Write-Host "RDP: ${Server}:$($Pair.device.rdp_port)"
    Write-Host "Туннель: OpenSSH"
    Write-Host "Задача: $TaskName"
    Write-Host 'Сертификат RDP: автоматическое управление'
    Write-Host "Лог: $BaseDir\agent.log"
}
catch {
    $InstallFailure = $_
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask `
        -TaskName $TaskName `
        -Confirm:$false `
        -ErrorAction SilentlyContinue
    Stop-HermesProcesses

    $ServerRegistrationCleared = -not $PairRequestStarted
    if ($Pair -and $Pair.device.id -and $Pair.device.token) {
        try {
            [void](Invoke-PinnedPost `
                -Client $Http `
                -Url (
                    "$ApiBase/v1/devices/" +
                    "$($Pair.device.id)/revoke-self"
                ) `
                -Token ([string]$Pair.device.token) `
                -Body @{ reason = 'client-install-failed' })
            $ServerRegistrationCleared = $true
        }
        catch {
            Write-Warning (
                'Не удалось автоматически отозвать неудачную регистрацию. ' +
                'Локальная identity сохранена для безопасного ручного удаления.'
            )
        }
    }

    if ($ServerRegistrationCleared) {
        Restore-InstallSnapshot `
            -BasePath $BaseDir `
            -SnapshotPath $BackupDir `
            -BaseExistedBefore $BaseDirExistedBefore `
            -BackupRootExistedBefore $BackupRootExistedBefore
    }
    elseif ($PairRequestStarted -and -not $Pair) {
        Write-Warning (
            'Pairing-запрос был отправлен, но итог сервера неизвестен. ' +
            'Локальные credentials сохранены; проверь устройство в Telegram.'
        )
    }

    throw $InstallFailure
}
finally {
    if ($Http) {
        $Http.Dispose()
    }
    Remove-Item `
        -LiteralPath $AgentCandidate, $CertSetupCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
