param(
    [string]$RepositoryRef = 'main'
)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bakunity/RDP'
$BaseDir = 'C:\ProgramData\HermesRDP'
$Target = Join-Path $BaseDir 'BakunityAccessHost.ps1'
$Candidate = Join-Path ([IO.Path]::GetTempPath()) (
    "BakunityAccessHost-$([Guid]::NewGuid().ToString('N')).ps1"
)

function Resolve-RepositorySha {
    param([string]$Ref)
    if ($Ref -match '^[0-9a-fA-F]{40}$') {
        return $Ref.ToLowerInvariant()
    }
    $Encoded = [Uri]::EscapeDataString($Ref)
    $Commit = Invoke-RestMethod -UseBasicParsing -Uri (
        "https://api.github.com/repos/$Repo/commits/$Encoded"
    ) -Headers @{ Accept='application/vnd.github+json' }
    $Sha = [string]$Commit.sha
    if ($Sha -notmatch '^[0-9a-fA-F]{40}$') {
        throw 'Unable to resolve RepositoryRef.'
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

function Set-AccessHostAcl {
    param([string]$Path)
    $Acl = Get-Acl -LiteralPath $Path
    $Acl.SetSecurityDescriptorSddlForm(
        'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)'
    )
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

$ResolvedSha = Resolve-RepositorySha -Ref $RepositoryRef
$Url = (
    "https://raw.githubusercontent.com/$Repo/" +
    "$ResolvedSha/client/BakunityAccessHost.ps1"
)

try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Candidate
    Assert-PowerShellFile -Path $Candidate
    New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
    Copy-Item -LiteralPath $Candidate -Destination $Target -Force
    Set-AccessHostAcl -Path $Target
    Write-Host "ACCESS_HOST_REF=$ResolvedSha"
    Write-Host "ACCESS_HOST=$Target"
    Write-Host 'ACCESS_HOST_SETUP=PASS' -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $Candidate -Force -ErrorAction SilentlyContinue
}
