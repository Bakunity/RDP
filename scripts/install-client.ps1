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

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$ConfigPath = Join-Path $BaseDir 'device.json'
$PrivateKeyPath = Join-Path $BaseDir 'id_ed25519'
$PublicKeyPath = "$PrivateKeyPath.pub"
$AgentPath = Join-Path $BaseDir 'HermesRdpAgent.ps1'
$RotationPath = Join-Path $BaseDir 'HermesRdpCertRotation.ps1'
$SyncPath = Join-Path $BaseDir 'sync-rdp-certificate.ps1'
$AgentTaskName = 'Hermes RDP Agent'
$RotationTaskName = 'Hermes RDP Certificate Rotation'
$ReplaceCandidate = Join-Path ([IO.Path]::GetTempPath()) (
    "HermesRdpInstallReplace-$([Guid]::NewGuid().ToString('N')).ps1"
)
$RepairCandidate = Join-Path ([IO.Path]::GetTempPath()) (
    "HermesRdpInstallSelfHeal-$([Guid]::NewGuid().ToString('N')).ps1"
)

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

function Test-HermesInstallComplete {
    foreach ($Path in @(
        $ConfigPath,
        $PrivateKeyPath,
        $PublicKeyPath,
        $AgentPath,
        $RotationPath,
        $SyncPath
    )) {
        if (-not (Test-Path -LiteralPath $Path)) {
            return $false
        }
    }

    foreach ($TaskName in @($AgentTaskName, $RotationTaskName)) {
        if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
            return $false
        }
    }

    try {
        $Rdp = Get-CimInstance `
            -Namespace 'root/cimv2/TerminalServices' `
            -ClassName Win32_TSGeneralSetting `
            -Filter "TerminalName='RDP-tcp'"
        $Thumbprint = (([string]$Rdp.SSLCertificateSHA1Hash) `
            -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
        if ([int]$Rdp.SSLCertificateSHA1HashType -ne 3 -or $Thumbprint.Length -ne 40) {
            return $false
        }
        $Certificate = Get-ChildItem -LiteralPath 'Cert:\LocalMachine\My' |
            Where-Object {
                (([string]$_.Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()) `
                    -eq $Thumbprint
            } |
            Select-Object -First 1
        if (-not $Certificate -or -not $Certificate.HasPrivateKey) {
            return $false
        }
        if ($Certificate.NotAfter -le (Get-Date)) {
            return $false
        }
    }
    catch {
        return $false
    }

    return $true
}

function Invoke-SameServerSelfHeal {
    param(
        [object]$Config,
        [string]$ResolvedSha
    )

    $RepairUrl = (
        "https://raw.githubusercontent.com/$Repo/" +
        "$ResolvedSha/scripts/repair-client.ps1"
    )
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $RepairUrl `
        -OutFile $RepairCandidate
    Assert-PowerShellFile -Path $RepairCandidate

    Write-Host '=== HERMES RDP SELF-HEAL ===' -ForegroundColor Cyan
    Write-Host (
        'Найдена неполная установка Hermes на этом же сервере. ' +
        'Восстанавливаю её без нового pairing и без смены identity.'
    )

    $NativePowerShell = Get-NativePowerShellPath
    & $NativePowerShell `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $RepairCandidate `
        -RepositoryRef $ResolvedSha `
        -ExpectedDeviceId ([string]$Config.device_id)
    if ($LASTEXITCODE -ne 0) {
        throw "Hermes self-heal Repair завершился с кодом $LASTEXITCODE"
    }

    if (-not (Test-HermesInstallComplete)) {
        throw 'Self-heal завершился, но финальные Hermes invariants не подтверждены.'
    }

    Write-Host 'SELF_HEAL=PASS' -ForegroundColor Green
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
try {
    $ExistingConfig = Get-ExistingHermesConfig
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
            if (Test-HermesInstallComplete) {
                throw (
                    "Hermes RDP уже полностью установлен на этом ПК и подключён " +
                    "к этому серверу (RDP-порт $($ExistingConfig.rdp_port)). " +
                    'Для обычного обслуживания используйте Repair/Update.'
                )
            }

            Invoke-SameServerSelfHeal `
                -Config $ExistingConfig `
                -ResolvedSha $ResolvedSha
            return
        }
    }

    $ReplaceUrl = (
        "https://raw.githubusercontent.com/$Repo/" +
        "$ResolvedSha/scripts/install-client-replace.ps1"
    )
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $ReplaceUrl `
        -OutFile $ReplaceCandidate
    Assert-PowerShellFile -Path $ReplaceCandidate

    $Params = @{
        Server = $Server
        PairCode = $PairCode
        Fingerprint = $Fingerprint
        ApiPort = $ApiPort
        RepositoryRef = $ResolvedSha
    }
    if ($PSBoundParameters.ContainsKey('Name')) {
        $Params.Name = $Name
    }
    if ($ReplaceExisting) {
        $Params.ReplaceExisting = $true
    }

    & $ReplaceCandidate @Params

    if (-not (Test-HermesInstallComplete)) {
        throw 'Fresh/REPLACE завершился, но финальные Hermes invariants не подтверждены.'
    }
    Write-Host 'INSTALL_INVARIANTS=PASS' -ForegroundColor Green
}
finally {
    Remove-Item `
        -LiteralPath $ReplaceCandidate, $RepairCandidate `
        -Force `
        -ErrorAction SilentlyContinue
}
