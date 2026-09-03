[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RawArguments
)
$ErrorActionPreference = 'Stop'
function Write-CaptureJson { param([hashtable]$Value) [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress)) }
$Platform = $null
$TitleHint = $null
$rawPid = $null
$Output = $null
$hasTitleHint = $false
for ($index = 0; $index -lt $RawArguments.Count; $index += 2) {
    if ($index + 1 -ge $RawArguments.Count) { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='Unsupported argument' }; exit 2 }
    $name = [string]$RawArguments[$index]
    $value = [string]$RawArguments[$index + 1]
    if ($name -eq '-Platform' -and $null -eq $Platform) { $Platform = $value }
    elseif ($name -eq '-Pid' -and $null -eq $rawPid) { $rawPid = $value }
    elseif ($name -eq '-TitleHint' -and $null -eq $TitleHint) { $TitleHint = $value; $hasTitleHint = $true }
    elseif ($name -eq '-Output' -and $null -eq $Output) { $Output = $value }
    else { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='Unsupported argument' }; exit 2 }
}
if ($Platform -notin @('qgis', 'knime')) { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='Unsupported platform' }; exit 2 }
$parsedTargetPid = $null
if ($null -ne $rawPid) {
    [long]$candidatePid = 0
    if ([string]::IsNullOrWhiteSpace($rawPid) -or -not [long]::TryParse($rawPid, [ref]$candidatePid) -or $candidatePid -lt 1) { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='Pid must be a positive integer' }; exit 2 }
    $parsedTargetPid = $candidatePid
}
if ($hasTitleHint -and ([string]::IsNullOrWhiteSpace($TitleHint) -or $TitleHint.Length -gt 256)) { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='TitleHint must be a non-empty string up to 256 characters' }; exit 2 }
if ([string]::IsNullOrWhiteSpace($Output)) { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='Output must be a non-empty path' }; exit 2 }
$OutputPath = [System.IO.Path]::GetFullPath($Output)
if (-not [System.IO.Path]::IsPathRooted($OutputPath)) { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic='Output must be an absolute path' }; exit 2 }

if (-not ('NativeWindow' -as [type])) { Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Diagnostics; using System.Runtime.InteropServices; using System.Text;
public sealed class WindowInfo { public long Pid; public string ProcessName; public string Title; public IntPtr Handle; }
public static class NativeWindow {
 private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
 [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
 [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hWnd);
 [DllImport("user32.dll")] private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
 [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
 public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
 public static List<WindowInfo> EnumerateTopLevelWindows() { var result=new List<WindowInfo>(); EnumWindows((h,l)=>{ if(!IsWindowVisible(h))return true; var title=new StringBuilder(512); if(GetWindowText(h,title,title.Capacity)==0)return true; uint pid; GetWindowThreadProcessId(h,out pid); try { var p=Process.GetProcessById((int)pid); result.Add(new WindowInfo { Pid=pid, ProcessName=p.ProcessName, Title=title.ToString(), Handle=h }); } catch {} return true; },IntPtr.Zero); return result; }
}
'@ }
function Normalize-WindowTitle { param([string]$Value) if ([string]::IsNullOrWhiteSpace($Value)) { return $null }; return $Value.Trim().Normalize([Text.NormalizationForm]::FormKC).ToUpperInvariant() }
function Get-TopLevelWindows { if ($env:QWEN_GIS_FOCUS_WINDOW_FIXTURE) { return @(ConvertFrom-Json -InputObject $env:QWEN_GIS_FOCUS_WINDOW_FIXTURE) }; return @([NativeWindow]::EnumerateTopLevelWindows()) }
$allowedNames = if ($Platform -eq 'qgis') { @('qgis-bin', 'qgis-ltr-bin', 'qgis') } else { @('knime', 'knime64') }
$windows = @(Get-TopLevelWindows | Where-Object { $allowedNames -contains $_.ProcessName })
if ($windows.Count -eq 0) { Write-CaptureJson @{ status='not-running'; platform=$Platform }; exit 0 }
$target = $null
if ($null -ne $parsedTargetPid) { $matches=@($windows | Where-Object { $_.Pid -eq $parsedTargetPid }); if ($matches.Count -eq 1) { $target=$matches[0] } }
if ($null -eq $target -and $hasTitleHint) { $hint=Normalize-WindowTitle $TitleHint; $matches=@($windows | Where-Object { (Normalize-WindowTitle $_.Title) -eq $hint }); if ($matches.Count -eq 1) { $target=$matches[0] } }
if ($null -eq $target -and $windows.Count -eq 1) { $target=$windows[0] }
if ($null -eq $target) { Write-CaptureJson @{ status='ambiguous'; platform=$Platform; diagnostic='Multiple allowlisted top-level windows match without a decisive hint' }; exit 3 }
try {
    [NativeWindow]::ShowWindowAsync($target.Handle, 9) | Out-Null
    Start-Sleep -Milliseconds 120
    $parent = [System.IO.Path]::GetDirectoryName($OutputPath)
    if (-not [string]::IsNullOrWhiteSpace($parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $rect = New-Object NativeWindow+RECT
    if (-not [NativeWindow]::GetWindowRect($target.Handle, [ref]$rect)) { throw 'GetWindowRect failed' }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -le 0 -or $height -le 0) { throw 'Target window has zero or negative size' }
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $hdc = $graphics.GetHdc()
    $captured = [NativeWindow]::PrintWindow($target.Handle, $hdc, 2)
    if (-not $captured) { $captured = [NativeWindow]::PrintWindow($target.Handle, $hdc, 1) }
    $graphics.ReleaseHdc($hdc)
    $graphics.Dispose()
    if (-not $captured) { $bitmap.Dispose(); throw 'PrintWindow capture failed' }
    $bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    Write-CaptureJson @{ status='ok'; platform=$Platform; path=$OutputPath; pid=$target.Pid; title=$target.Title }
    exit 0
} catch { Write-CaptureJson @{ status='error'; platform=$Platform; diagnostic=$_.Exception.Message }; exit 1 }
