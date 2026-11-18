$ErrorActionPreference = 'Stop'

$Script = Join-Path $PSScriptRoot '..\client\BakunityAccessHost.ps1'
$Port = 48401
$Process = Start-Process `
    -FilePath 'powershell.exe' `
    -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $Script + '"'),
        '-Port', [string]$Port
    ) `
    -WindowStyle Hidden `
    -PassThru

try {
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        Start-Sleep -Milliseconds 250
        if ($Process.HasExited) {
            throw "BakunityAccessHost exited early: $($Process.ExitCode)"
        }
        $Probe = New-Object Net.Sockets.TcpClient
        try {
            $Async = $Probe.BeginConnect('127.0.0.1', $Port, $null, $null)
            if ($Async.AsyncWaitHandle.WaitOne(300, $false)) {
                $Probe.EndConnect($Async)
                $Ready = $true
                break
            }
        }
        catch {
        }
        finally {
            $Probe.Dispose()
        }
    }
    if (-not $Ready) {
        throw 'BakunityAccessHost did not listen on loopback.'
    }

    $Client = New-Object Net.Sockets.TcpClient('127.0.0.1', $Port)
    try {
        $Stream = $Client.GetStream()
        try {
            $Payload = [Text.Encoding]::ASCII.GetBytes("PING`n")
            $Stream.Write($Payload, 0, $Payload.Length)
            $Header = New-Object byte[] 4
            $Read = $Stream.Read($Header, 0, 4)
            if ($Read -ne 4) {
                throw 'Live Screen PING frame header is incomplete.'
            }
            if (-not [BitConverter]::IsLittleEndian) {
                [Array]::Reverse($Header)
            }
            $Length = [BitConverter]::ToInt32($Header, 0)
            if ($Length -ne 2) {
                throw "Unexpected Live Screen PING length: $Length"
            }
            $Body = New-Object byte[] $Length
            $Read = $Stream.Read($Body, 0, $Body.Length)
            if ($Read -ne $Length) {
                throw 'Live Screen PING frame body is incomplete.'
            }
            $Text = [Text.Encoding]::UTF8.GetString($Body)
            if ($Text -ne 'OK') {
                throw "Unexpected Live Screen PING response: $Text"
            }
        }
        finally {
            $Stream.Dispose()
        }
    }
    finally {
        $Client.Dispose()
    }

    $SnapshotClient = New-Object Net.Sockets.TcpClient('127.0.0.1', $Port)
    try {
        $SnapshotStream = $SnapshotClient.GetStream()
        try {
            $Payload = [Text.Encoding]::ASCII.GetBytes("SNAPSHOT`n")
            $SnapshotStream.Write($Payload, 0, $Payload.Length)

            function Read-TestFrame {
                param([System.Net.Sockets.NetworkStream]$Stream)
                $Header = New-Object byte[] 4
                $Offset = 0
                while ($Offset -lt 4) {
                    $Read = $Stream.Read($Header, $Offset, 4 - $Offset)
                    if ($Read -le 0) { throw 'Snapshot frame header ended early.' }
                    $Offset += $Read
                }
                if (-not [BitConverter]::IsLittleEndian) {
                    [Array]::Reverse($Header)
                }
                $Length = [BitConverter]::ToInt32($Header, 0)
                if ($Length -lt 1 -or $Length -gt 16777216) {
                    throw "Invalid snapshot frame length: $Length"
                }
                $Body = New-Object byte[] $Length
                $Offset = 0
                while ($Offset -lt $Length) {
                    $Read = $Stream.Read(
                        $Body,
                        $Offset,
                        $Length - $Offset
                    )
                    if ($Read -le 0) { throw 'Snapshot frame body ended early.' }
                    $Offset += $Read
                }
                return $Body
            }

            $MetaBytes = Read-TestFrame -Stream $SnapshotStream
            $Meta = (
                [Text.Encoding]::UTF8.GetString($MetaBytes) |
                ConvertFrom-Json
            )
            if (
                [int]$Meta.width -le 0 -or
                [int]$Meta.height -le 0
            ) {
                throw 'Snapshot metadata has invalid dimensions.'
            }

            $Jpeg = Read-TestFrame -Stream $SnapshotStream
            if (
                $Jpeg.Length -lt 4 -or
                $Jpeg[0] -ne 0xFF -or
                $Jpeg[1] -ne 0xD8
            ) {
                throw 'Snapshot payload is not a JPEG image.'
            }
        }
        finally {
            $SnapshotStream.Dispose()
        }
    }
    finally {
        $SnapshotClient.Dispose()
    }

    Write-Host 'LIVE_SCREEN_SNAPSHOT_SMOKE=PASS'
    Write-Host 'LIVE_SCREEN_LOOPBACK_SMOKE=PASS'
}
finally {
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}
