# Снимок окна процесса (только область его окна): .\scripts\capture_window.ps1 -Process gmagc-desktop -Out window.png
param([string]$Process = "gmagc-desktop", [string]$Out = "window.png")

Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class GmagcWin32 {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@

[GmagcWin32]::SetProcessDPIAware() | Out-Null
$p = Get-Process $Process -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { throw "Окно процесса $Process не найдено" }
[GmagcWin32]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[GmagcWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 700
$r = New-Object GmagcWin32+RECT
[GmagcWin32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$width = $r.Right - $r.Left
$height = $r.Bottom - $r.Top
$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($r.Left, $r.Top, 0, 0, $bitmap.Size)
$bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Host "Снимок окна: $Out ($width x $height)"
