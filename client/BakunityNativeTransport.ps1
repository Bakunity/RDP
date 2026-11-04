$script:BakunityNativeTransportRoot = 'C:\ProgramData\BakunityRDP\Transport'
$script:BakunityNativeTransportExe = Join-Path $script:BakunityNativeTransportRoot 'BakunityTransport.exe'
$script:BakunityNativeTransportConfig = Join-Path $script:BakunityNativeTransportRoot 'config.json'
$script:BakunityNativeTransportRef = Join-Path $script:BakunityNativeTransportRoot 'build-ref.txt'
$script:BakunityNativeTransportTask = 'Bakunity Transport'
$script:BakunityNativeTransportControl = 'http://127.0.0.1:48389'
$script:BakunityGoVersion = '1.26.10'
$script:BakunityGoAmd64Sha256 = '7ecd2d7260e82c59bcbd7f1077a07cee2dea607295b858df67195a1e4e09629b'

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

function Install-BakunityNativeTransportBinary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRef
    )

    $RepositoryRef = ([string]$RepositoryRef).Trim().ToLowerInvariant()
    if ($RepositoryRef -notmatch '^[0-9a-f]{40}$') {
        throw 'RepositoryRef must be an immutable 40-character SHA.'
    }

    $ExistingRef = if (Test-Path -LiteralPath $script:BakunityNativeTransportRef) {
        (Get-Content -LiteralPath $script:BakunityNativeTransportRef -Raw).Trim().ToLowerInvariant()
    } else { '' }
    if (
        $ExistingRef -eq $RepositoryRef -and
        (Test-Path -LiteralPath $script:BakunityNativeTransportExe)
    ) {
        return
    }

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Bakunity Transport native build currently requires Windows x64.'
    }
    $Arch = "$env:PROCESSOR_ARCHITECTURE $env:PROCESSOR_ARCHITEW6432".ToUpperInvariant()
    if ($Arch.Contains('ARM64')) {
        throw 'Bakunity Transport ARM64 build is not enabled yet.'
    }

    $Work = Join-Path ([IO.Path]::GetTempPath()) (
        'BakunityTransportBuild-' + [Guid]::NewGuid().ToString('N')
    )
    $GoZip = Join-Path $Work 'go.zip'
    $SourceArchive = Join-Path $Work 'source.tar.gz'
    $GoRoot = Join-Path $Work 'go'
    $SourceRoot = Join-Path $Work 'source'
    $Candidate = Join-Path $Work 'BakunityTransport.exe'

    New-Item -ItemType Directory -Path $Work,$SourceRoot -Force | Out-Null
    try {
        $GoUrl = (
            'https://go.dev/dl/go' +
            $script:BakunityGoVersion +
            '.windows-amd64.zip'
        )
        Invoke-WebRequest -UseBasicParsing -Uri $GoUrl -OutFile $GoZip
        $ActualGoHash = (
            Get-FileHash -LiteralPath $GoZip -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if ($ActualGoHash -ne $script:BakunityGoAmd64Sha256) {
            throw 'Pinned Go toolchain checksum mismatch.'
        }
        Expand-Archive -LiteralPath $GoZip -DestinationPath $Work -Force

        $ArchiveUrl = (
            'https://codeload.github.com/bakunity/RDP/tar.gz/' +
            $RepositoryRef
        )
        Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $SourceArchive

        $Tar = Join-Path $env:WINDIR 'System32\tar.exe'
        if (-not (Test-Path -LiteralPath $Tar)) {
            throw 'Windows tar.exe is required.'
        }
        & $Tar -xzf $SourceArchive -C $SourceRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Source archive extraction failed: $LASTEXITCODE"
        }

        $Checkout = Get-ChildItem -LiteralPath $SourceRoot -Directory |
            Select-Object -First 1
        if (-not $Checkout) {
            throw 'Bakunity source checkout was not extracted.'
        }
        $Module = Join-Path $Checkout.FullName 'native-transport'
        if (-not (Test-Path -LiteralPath (Join-Path $Module 'go.mod'))) {
            throw 'Bakunity native transport module is missing.'
        }

        $GoExe = Join-Path $GoRoot 'bin\go.exe'
        $OldGoModCache = $env:GOMODCACHE
        $OldGoCache = $env:GOCACHE
        $env:GOMODCACHE = Join-Path $Work 'gomod'
        $env:GOCACHE = Join-Path $Work 'gocache'
        try {
            Push-Location $Module
            try {
                & $GoExe build -trimpath -ldflags '-s -w' -o $Candidate '.\cmd\bakunity-transport'
                if ($LASTEXITCODE -ne 0) {
                    throw "Bakunity Transport build failed: $LASTEXITCODE"
                }
            }
            finally {
                Pop-Location
            }
        }
        finally {
            $env:GOMODCACHE = $OldGoModCache
            $env:GOCACHE = $OldGoCache
        }

        if (-not (Test-Path -LiteralPath $Candidate)) {
            throw 'Bakunity Transport binary was not produced.'
        }

        New-Item -ItemType Directory -Path $script:BakunityNativeTransportRoot -Force | Out-Null
        Stop-BakunityNativeTransportTask
        Copy-Item -LiteralPath $Candidate -Destination $script:BakunityNativeTransportExe -Force
        Set-BakunityNativeExecutableAcl -Path $script:BakunityNativeTransportExe
        Set-Content -LiteralPath $script:BakunityNativeTransportRef -Value $RepositoryRef -Encoding ASCII
        Set-BakunityNativeSecretAcl -Path $script:BakunityNativeTransportRef

        foreach ($Name in @(
            'Bakunity Transport TCP',
            'Bakunity Transport UDP'
        )) {
            Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
        }
        New-NetFirewallRule -DisplayName 'Bakunity Transport TCP' -Direction Inbound -Action Allow -Program $script:BakunityNativeTransportExe -Protocol TCP -Profile Any | Out-Null
        New-NetFirewallRule -DisplayName 'Bakunity Transport UDP' -Direction Inbound -Action Allow -Program $script:BakunityNativeTransportExe -Protocol UDP -Profile Any | Out-Null
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
    [ordered]@{
        role = $Role
        identity_path = (
            Join-Path $script:BakunityNativeTransportRoot 'identity.key'
        )
        relay_addr = $RelayAddr
        control_addr = '127.0.0.1:48389'
        target = '127.0.0.1:3389'
        shared_secret = $SharedSecret
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ConfigTemp -Encoding UTF8
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
