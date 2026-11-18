param(
    [int]$Port = 48400
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$Interop = @'
using System;
using System.Runtime.InteropServices;

public static class BakunityAccessInput
{
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT {
        public uint type;
        public InputUnion U;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct InputUnion {
        [FieldOffset(0)] public MOUSEINPUT mi;
        [FieldOffset(0)] public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [DllImport("user32.dll", SetLastError=true)]
    static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    const uint INPUT_MOUSE = 0;
    const uint INPUT_KEYBOARD = 1;
    const uint MOUSEEVENTF_MOVE = 0x0001;
    const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    const uint MOUSEEVENTF_LEFTUP = 0x0004;
    const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    const uint MOUSEEVENTF_RIGHTUP = 0x0010;
    const uint MOUSEEVENTF_WHEEL = 0x0800;
    const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
    const uint KEYEVENTF_KEYUP = 0x0002;
    const uint KEYEVENTF_UNICODE = 0x0004;

    static void SendMouse(uint flags, int x, int y, uint data) {
        var input = new INPUT();
        input.type = INPUT_MOUSE;
        input.U.mi.dx = x;
        input.U.mi.dy = y;
        input.U.mi.mouseData = data;
        input.U.mi.dwFlags = flags;
        SendInput(1, new [] { input }, Marshal.SizeOf(typeof(INPUT)));
    }

    public static void MoveAbsolute(int x, int y, int width, int height) {
        if (width <= 1 || height <= 1) return;
        int nx = Math.Max(0, Math.Min(65535, (int)Math.Round(x * 65535.0 / (width - 1))));
        int ny = Math.Max(0, Math.Min(65535, (int)Math.Round(y * 65535.0 / (height - 1))));
        SendMouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny, 0);
    }

    public static void MouseButton(string button, bool down) {
        uint flags = 0;
        if (button == "left") flags = down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
        else if (button == "right") flags = down ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_RIGHTUP;
        if (flags != 0) SendMouse(flags, 0, 0, 0);
    }

    public static void Wheel(int delta) {
        SendMouse(MOUSEEVENTF_WHEEL, 0, 0, unchecked((uint)delta));
    }

    public static void Key(ushort vk, bool down) {
        var input = new INPUT();
        input.type = INPUT_KEYBOARD;
        input.U.ki.wVk = vk;
        input.U.ki.dwFlags = down ? 0u : KEYEVENTF_KEYUP;
        SendInput(1, new [] { input }, Marshal.SizeOf(typeof(INPUT)));
    }

    public static void Text(string text) {
        foreach (char ch in text ?? String.Empty) {
            var down = new INPUT();
            down.type = INPUT_KEYBOARD;
            down.U.ki.wScan = ch;
            down.U.ki.dwFlags = KEYEVENTF_UNICODE;
            var up = down;
            up.U.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            SendInput(2, new [] { down, up }, Marshal.SizeOf(typeof(INPUT)));
        }
    }
}
'@

if (-not ('BakunityAccessInput' -as [type])) {
    Add-Type -TypeDefinition $Interop -Language CSharp
}

function Write-Frame {
    param(
        [System.Net.Sockets.NetworkStream]$Stream,
        [byte[]]$Bytes
    )
    $Length = [BitConverter]::GetBytes([int]$Bytes.Length)
    if (-not [BitConverter]::IsLittleEndian) { [Array]::Reverse($Length) }
    $Stream.Write($Length, 0, $Length.Length)
    if ($Bytes.Length -gt 0) {
        $Stream.Write($Bytes, 0, $Bytes.Length)
    }
    $Stream.Flush()
}

function Read-Exact {
    param(
        [System.Net.Sockets.NetworkStream]$Stream,
        [int]$Length
    )
    $Buffer = New-Object byte[] $Length
    $Offset = 0
    while ($Offset -lt $Length) {
        $Read = $Stream.Read($Buffer, $Offset, $Length - $Offset)
        if ($Read -le 0) { throw 'Unexpected end of stream.' }
        $Offset += $Read
    }
    return $Buffer
}

function Read-Line {
    param([System.Net.Sockets.NetworkStream]$Stream)
    $Bytes = New-Object 'System.Collections.Generic.List[byte]'
    while ($Bytes.Count -lt 4096) {
        $One = Read-Exact -Stream $Stream -Length 1
        if ($One[0] -eq 10) { break }
        if ($One[0] -ne 13) { $Bytes.Add($One[0]) }
    }
    return [Text.Encoding]::UTF8.GetString($Bytes.ToArray())
}

function Get-DesktopBounds {
    $Screens = [Windows.Forms.Screen]::AllScreens
    if (-not $Screens -or $Screens.Count -eq 0) {
        throw 'No interactive desktop screens are available.'
    }
    $Left = ($Screens | ForEach-Object { $_.Bounds.Left } | Measure-Object -Minimum).Minimum
    $Top = ($Screens | ForEach-Object { $_.Bounds.Top } | Measure-Object -Minimum).Minimum
    $Right = ($Screens | ForEach-Object { $_.Bounds.Right } | Measure-Object -Maximum).Maximum
    $Bottom = ($Screens | ForEach-Object { $_.Bounds.Bottom } | Measure-Object -Maximum).Maximum
    return [Drawing.Rectangle]::FromLTRB($Left, $Top, $Right, $Bottom)
}

function Get-Snapshot {
    $Bounds = Get-DesktopBounds
    $Bitmap = New-Object Drawing.Bitmap $Bounds.Width, $Bounds.Height, ([Drawing.Imaging.PixelFormat]::Format24bppRgb)
    try {
        $Graphics = [Drawing.Graphics]::FromImage($Bitmap)
        try {
            $Graphics.CopyFromScreen(
                $Bounds.Left,
                $Bounds.Top,
                0,
                0,
                $Bounds.Size,
                [Drawing.CopyPixelOperation]::SourceCopy
            )
        }
        finally {
            $Graphics.Dispose()
        }

        $Memory = New-Object IO.MemoryStream
        try {
            $Codec = [Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
                Where-Object { $_.MimeType -eq 'image/jpeg' } |
                Select-Object -First 1
            $Encoder = [Drawing.Imaging.Encoder]::Quality
            $Params = New-Object Drawing.Imaging.EncoderParameters 1
            $Params.Param[0] = New-Object Drawing.Imaging.EncoderParameter($Encoder, [long]72)
            try {
                $Bitmap.Save($Memory, $Codec, $Params)
            }
            finally {
                $Params.Dispose()
            }
            return @{
                bytes = $Memory.ToArray()
                width = $Bounds.Width
                height = $Bounds.Height
                left = $Bounds.Left
                top = $Bounds.Top
            }
        }
        finally {
            $Memory.Dispose()
        }
    }
    finally {
        $Bitmap.Dispose()
    }
}

function Invoke-Input {
    param([object]$Body)

    $Bounds = Get-DesktopBounds
    $Kind = ([string]$Body.kind).ToLowerInvariant()
    switch ($Kind) {
        'move' {
            $X = [int]$Body.x - $Bounds.Left
            $Y = [int]$Body.y - $Bounds.Top
            [BakunityAccessInput]::MoveAbsolute($X, $Y, $Bounds.Width, $Bounds.Height)
        }
        'button' {
            [BakunityAccessInput]::MouseButton(
                ([string]$Body.button).ToLowerInvariant(),
                [bool]$Body.down
            )
        }
        'wheel' {
            [BakunityAccessInput]::Wheel([int]$Body.delta)
        }
        'key' {
            [BakunityAccessInput]::Key([uint16]$Body.vk, [bool]$Body.down)
        }
        'text' {
            [BakunityAccessInput]::Text([string]$Body.text)
        }
        default {
            throw "Unsupported input kind: $Kind"
        }
    }
}

$Listener = [Net.Sockets.TcpListener]::new(
    [Net.IPAddress]::Loopback,
    $Port
)
$Listener.Start()
try {
    while ($true) {
        $Client = $Listener.AcceptTcpClient()
        try {
            $Client.NoDelay = $true
            $Stream = $Client.GetStream()
            $Stream.ReadTimeout = 5000
            $Stream.WriteTimeout = 5000
            $Line = Read-Line -Stream $Stream
            if ($Line -eq 'PING') {
                Write-Frame -Stream $Stream -Bytes ([Text.Encoding]::UTF8.GetBytes('OK'))
                continue
            }
            if ($Line -eq 'SNAPSHOT') {
                $Shot = Get-Snapshot
                $Meta = [ordered]@{
                    width = [int]$Shot.width
                    height = [int]$Shot.height
                    left = [int]$Shot.left
                    top = [int]$Shot.top
                } | ConvertTo-Json -Compress
                Write-Frame -Stream $Stream -Bytes ([Text.Encoding]::UTF8.GetBytes($Meta))
                Write-Frame -Stream $Stream -Bytes ([byte[]]$Shot.bytes)
                continue
            }
            if ($Line -match '^INPUT\s+(\d+)$') {
                $Length = [int]$Matches[1]
                if ($Length -lt 2 -or $Length -gt 65536) {
                    throw 'Invalid input payload length.'
                }
                $Json = [Text.Encoding]::UTF8.GetString(
                    (Read-Exact -Stream $Stream -Length $Length)
                )
                $Body = $Json | ConvertFrom-Json
                Invoke-Input -Body $Body
                Write-Frame -Stream $Stream -Bytes ([Text.Encoding]::UTF8.GetBytes('OK'))
                continue
            }
            throw 'Unsupported Bakunity Access command.'
        }
        catch {
            try {
                if ($Stream) {
                    Write-Frame -Stream $Stream -Bytes (
                        [Text.Encoding]::UTF8.GetBytes(
                            'ERROR:' + $_.Exception.Message
                        )
                    )
                }
            }
            catch {}
        }
        finally {
            if ($Stream) { $Stream.Dispose() }
            $Client.Dispose()
        }
    }
}
finally {
    $Listener.Stop()
}
