$script:BakunityTailscaleVersion = '1.104.5'
$script:BakunityMeshRoot = 'C:\ProgramData\BakunityRDP\Mesh'
$script:BakunityMeshOwnerPath = Join-Path $script:BakunityMeshRoot 'owned.json'

function Get-BakunityNativeSystem32 {
    $System32 = Join-Path $env:WINDIR 'System32'
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        $System32 = Join-Path $env:WINDIR 'Sysnative'
    }
    return $System32
}

function Set-BakunitySecretAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Read-BakunityMeshOwner {
    if (-not (Test-Path -LiteralPath $script:BakunityMeshOwnerPath)) { return $null }
    try { return Get-Content -LiteralPath $script:BakunityMeshOwnerPath -Raw | ConvertFrom-Json }
    catch { return $null }
}

function Write-BakunityMeshOwner {
    param([string[]]$Roles, [string]$ControlUrl, [string]$Version)
    New-Item -ItemType Directory -Path $script:BakunityMeshRoot -Force | Out-Null
    $Temp = "$script:BakunityMeshOwnerPath.tmp"
    [ordered]@{
        owner = 'bakunity-rdp'
        roles = @($Roles | Sort-Object -Unique)
        control_url = [string]$ControlUrl
        tailscale_version = [string]$Version
        updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Temp -Encoding UTF8
    Set-BakunitySecretAcl -Path $Temp
    Move-Item -LiteralPath $Temp -Destination $script:BakunityMeshOwnerPath -Force
}

function Get-BakunityTailscaleExe {
    $Candidate = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $Candidate) { return $Candidate }
    return ''
}

function Get-BakunityWindowsPackageArch {
    if (-not [Environment]::Is64BitOperatingSystem) { return 'x86' }
    $Arch = "$env:PROCESSOR_ARCHITECTURE $env:PROCESSOR_ARCHITEW6432".ToUpperInvariant()
    if ($Arch.Contains('ARM64')) { return 'arm64' }
    return 'amd64'
}

function Get-BakunityTailscaleVersion {
    param([string]$Exe)
    if (-not $Exe) { return '' }
    try {
        $Raw = @(& $Exe version 2>$null)
        if ($LASTEXITCODE -ne 0 -or $Raw.Count -eq 0) { return '' }
        $First = ([string]$Raw[0]).Trim()
        if ($First -match '([0-9]+\.[0-9]+\.[0-9]+)') { return [string]$Matches[1] }
    }
    catch {}
    return ''
}

function Get-BakunityTailscaleStatus {
    $Exe = Get-BakunityTailscaleExe
    $Owner = Read-BakunityMeshOwner
    if (-not $Exe) {
        return [pscustomobject]@{
            installed=$false; owned=$false; conflict=$false; online=$false
            ipv4=''; version=''; roles=@(); control_url=''
        }
    }

    $Version = Get-BakunityTailscaleVersion -Exe $Exe
    $Online = $false
    $IPv4 = ''
    try {
        $Raw = @(& $Exe status --json 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Raw.Count -gt 0) {
            $Status = ($Raw -join [Environment]::NewLine) | ConvertFrom-Json
            $Online = ([string]$Status.BackendState -eq 'Running')
            $Addresses = @($Status.TailscaleIPs | Where-Object { ([string]$_) -match '^\d+\.\d+\.\d+\.\d+$' })
            $IPv4 = [string]($Addresses | Select-Object -First 1)
        }
    }
    catch {
        $Online = $false
        $IPv4 = ''
    }

    $Owned = [bool]($Owner -and [string]$Owner.owner -eq 'bakunity-rdp')
    $Roles = if ($Owned) { @($Owner.roles) } else { @() }
    $ControlUrl = if ($Owned) { [string]$Owner.control_url } else { '' }
    return [pscustomobject]@{
        installed=$true
        owned=$Owned
        conflict=(-not $Owned)
        online=$Online
        ipv4=$IPv4
        version=$Version
        roles=@($Roles)
        control_url=$ControlUrl
    }
}

function Install-BakunityTailscale {
    $Existing = Get-BakunityTailscaleExe
    if ($Existing) {
        if (-not (Read-BakunityMeshOwner)) {
            throw 'FOREIGN_TAILSCALE: existing Tailscale is not managed by Bakunity'
        }
        return $Existing
    }

    $Arch = Get-BakunityWindowsPackageArch
    $Version = $script:BakunityTailscaleVersion
    $Uri = "https://pkgs.tailscale.com/stable/tailscale-setup-$Version-$Arch.msi"
    $Msi = Join-Path ([IO.Path]::GetTempPath()) ("BakunityTailscale-$Version-$Arch-$([Guid]::NewGuid().ToString('N')).msi")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Msi
        $Signature = Get-AuthenticodeSignature -FilePath $Msi
        if ([string]$Signature.Status -ne 'Valid') {
            throw "Tailscale MSI signature is not valid: $($Signature.Status)"
        }

        $Msiexec = Join-Path (Get-BakunityNativeSystem32) 'msiexec.exe'
        $QuotedMsi = '"' + $Msi + '"'
        $Process = Start-Process -FilePath $Msiexec -ArgumentList @('/i', $QuotedMsi, '/qn', '/norestart') -Wait -PassThru
        if ($Process.ExitCode -notin @(0,3010)) {
            throw "Tailscale MSI failed with code $($Process.ExitCode)"
        }

        $Deadline = [DateTime]::UtcNow.AddSeconds(60)
        do {
            $Exe = Get-BakunityTailscaleExe
            if ($Exe) { break }
            Start-Sleep -Seconds 1
        } while ([DateTime]::UtcNow -lt $Deadline)
        if (-not $Exe) { throw 'Tailscale executable did not appear after installation.' }

        Write-BakunityMeshOwner -Roles @() -ControlUrl '' -Version (Get-BakunityTailscaleVersion -Exe $Exe)
        return $Exe
    }
    finally {
        Remove-Item -LiteralPath $Msi -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-BakunityMeshRole {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('host','connector')][string]$Role,
        [Parameter(Mandatory = $true)][object]$Bootstrap
    )

    $Before = Get-BakunityTailscaleStatus
    if ($Before.installed -and -not $Before.owned) {
        return [pscustomobject]@{ ok=$false; conflict=$true; message='FOREIGN_TAILSCALE' }
    }

    $Exe = Install-BakunityTailscale
    $Owner = Read-BakunityMeshOwner
    $ExistingRoles = if ($Owner) { @($Owner.roles) } else { @() }
    $RequiredRoles = @($ExistingRoles + $Role | Sort-Object -Unique)
    if ($Role -eq 'host' -and 'connector' -notin $RequiredRoles) { $RequiredRoles += 'connector' }

    $ControlUrl = ([string]$Bootstrap.control_url).Trim()
    $AuthKey = [string]$Bootstrap.auth_key
    $NodeName = ([string]$Bootstrap.node_name).Trim()
    if (-not $ControlUrl.StartsWith('https://') -or [string]::IsNullOrWhiteSpace($AuthKey) -or [string]::IsNullOrWhiteSpace($NodeName)) {
        throw 'Invalid Bakunity mesh bootstrap response.'
    }

    New-Item -ItemType Directory -Path $script:BakunityMeshRoot -Force | Out-Null
    $KeyFile = Join-Path $script:BakunityMeshRoot ("auth-$([Guid]::NewGuid().ToString('N')).key")
    try {
        Set-Content -LiteralPath $KeyFile -Value $AuthKey -Encoding ASCII -NoNewline
        Set-BakunitySecretAcl -Path $KeyFile
        $Arguments = @(
            'up',
            "--login-server=$ControlUrl",
            "--auth-key=file:$KeyFile",
            "--hostname=$NodeName",
            '--unattended',
            '--accept-dns=false',
            '--accept-routes=false',
            '--ssh=false',
            '--reset',
            '--force-reauth'
        )
        $Output = @(& $Exe @Arguments 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "tailscale up failed: $($Output -join ' ')" }
    }
    finally {
        Remove-Item -LiteralPath $KeyFile -Force -ErrorAction SilentlyContinue
        $AuthKey = $null
    }

    $Deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        $After = Get-BakunityTailscaleStatus
        if ($After.online -and $After.ipv4) { break }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $Deadline)

    $After = Get-BakunityTailscaleStatus
    if (-not $After.online -or -not $After.ipv4) {
        throw 'Bakunity mesh did not become online after enrollment.'
    }

    Write-BakunityMeshOwner -Roles $RequiredRoles -ControlUrl $ControlUrl -Version $After.version
    return [pscustomobject]@{ ok=$true; conflict=$false; message='ONLINE' }
}

function Test-BakunityMeshDirect {
    param([Parameter(Mandatory = $true)][string]$Target, [int]$Count = 5)
    $Exe = Get-BakunityTailscaleExe
    if (-not $Exe) {
        return [pscustomobject]@{ direct=$false; relay=$false; peer_relay=$false; latency_ms=0; detail='tailscale unavailable' }
    }

    $Output = @(& $Exe ping "--c=$Count" '--timeout=5s' $Target 2>&1)
    $Direct = $false
    $Relay = $false
    $PeerRelay = $false
    $Latency = 0
    foreach ($LineObject in $Output) {
        $Line = [string]$LineObject
        if ($Line -match 'via DERP\(') { $Relay = $true; continue }
        if ($Line -match 'via peer-relay\(') { $PeerRelay = $true; continue }
        if ($Line -match 'via ([0-9a-fA-F\.:]+):([0-9]+) in ([0-9]+)ms') {
            $Direct = $true
            $Latency = [int]$Matches[3]
        }
    }

    return [pscustomobject]@{
        direct=$Direct
        relay=$Relay
        peer_relay=$PeerRelay
        latency_ms=$Latency
        detail=[string]($Output | Select-Object -Last 1)
    }
}
