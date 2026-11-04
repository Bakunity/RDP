$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http

$InstallerPath = Join-Path $PSScriptRoot '..\scripts\install-client-core.ps1'
$InstallerText = Get-Content -LiteralPath $InstallerPath -Raw
$Match = [regex]::Match(
    $InstallerText,
    "(?s)\$PinnedHttpClientSource = @'\r?\n(.*?)\r?\n'@"
)
if (-not $Match.Success) {
    throw 'PinnedHttpClientSource was not found in install-client-core.ps1.'
}

if (-not ('HermesRdp.PinnedHttpClientFactory' -as [type])) {
    Add-Type `
        -TypeDefinition $Match.Groups[1].Value `
        -Language CSharp `
        -ReferencedAssemblies 'System.Net.Http.dll'
}

$Certificate = New-SelfSignedCertificate `
    -DnsName 'hermes-rdp-test.invalid' `
    -CertStoreLocation 'Cert:\CurrentUser\My'

try {
    $Sha = [Security.Cryptography.SHA256]::Create()
    try {
        $Expected = ([BitConverter]::ToString(
            $Sha.ComputeHash($Certificate.RawData)
        )).Replace('-', '')
    }
    finally {
        $Sha.Dispose()
    }

    if (-not [HermesRdp.PinnedHttpClientFactory]::ValidateCertificate(
        $Certificate,
        $Expected
    )) {
        throw 'Correct certificate fingerprint was rejected.'
    }

    if ([HermesRdp.PinnedHttpClientFactory]::ValidateCertificate(
        $Certificate,
        ('0' * 64)
    )) {
        throw 'Incorrect certificate fingerprint was accepted.'
    }

    $Client = [HermesRdp.PinnedHttpClientFactory]::Create($Expected)
    try {
        if ($Client.GetType().FullName -ne 'System.Net.Http.HttpClient') {
            throw 'Factory did not return HttpClient.'
        }
        if ([int]$Client.Timeout.TotalSeconds -ne 30) {
            throw 'Unexpected HttpClient timeout.'
        }
    }
    finally {
        $Client.Dispose()
    }
}
finally {
    Remove-Item -LiteralPath $Certificate.PSPath -Force -ErrorAction SilentlyContinue
}

Write-Host 'static-csharp-cert-pinning=PASS'
