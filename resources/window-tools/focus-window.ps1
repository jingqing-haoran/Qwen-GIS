[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RawArguments
)
$ErrorActionPreference = 'Stop'
function Write-FocusJson { param([hashtable]$Value) [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress)) }
$Platform = $null
$TitleHint = $null
$rawPid = $null
$hasTitleHint = $false
for ($index = 0; $index -lt $RawArguments.Count; $index += 2) {
    if ($index + 1 -ge $RawArguments.Count) { Write-FocusJson @{ status='error'; platform=$Platform; diagnostic='Unsupported argument' }; exit 2 }
    $name = [string]$RawArguments[$index]
    $value = [string]$RawArguments[$index + 1]
    if ($name -eq '-Platform' -and $null -eq $Platform) { $Platform = $value }
    elseif ($name -eq '-Pid' -and $null -eq $rawPid) { $rawPid = $value }
    elseif ($name -eq '-TitleHint' -and $null -eq $TitleHint) { $TitleHint = $value; $hasTitleHint = $true }
    else { Write-FocusJson @{ status='error'; platform=$Platform; diagnostic='Unsupported argument' }; exit 2 }
}
if ($Platform -notin @('qgis', 'knime')) { Write-FocusJson @{ status='error'; platform=$Platform; diagnostic='Unsupported platform' }; exit 2 }
$parsedTargetPid = $null
if ($null -ne $rawPid) {
    [long]$candidatePid = 0
    if ([string]::IsNullOrWhiteSpace($rawPid) -or -not [long]::TryParse($rawPid, [ref]$candidatePid) -or $candidatePid -lt 1) { Write-FocusJson @{ status='error'; platform=$Platform; diagnostic='Pid must be a positive integer' }; exit 2 }
    $parsedTargetPid = $candidatePid
}
if ($hasTitleHint -and ([string]::IsNullOrWhiteSpace($TitleHint) -or $TitleHint.Length -gt 256)) { Write-FocusJson @{ status='error'; platform=$Platform; diagnostic='TitleHint must be a non-empty string up to 256 characters' }; exit 2 }
if (-not ('NativeWindow' -as [type])) { Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Diagnostics; using System.Runtime.InteropServices; using System.Text;
public sealed class WindowInfo { public long Pid; public string ProcessName; public string Title; public IntPtr Handle; }
public static class NativeWindow {
 private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
 [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
 [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hWnd);
 [DllImport("user32.dll")] private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
 [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
 public static List<WindowInfo> EnumerateTopLevelWindows() { var result=new List<WindowInfo>(); EnumWindows((h,l)=>{ if(!IsWindowVisible(h))return true; var title=new StringBuilder(512); if(GetWindowText(h,title,title.Capacity)==0)return true; uint pid; GetWindowThreadProcessId(h,out pid); try { var p=Process.GetProcessById((int)pid); result.Add(new WindowInfo { Pid=pid, ProcessName=p.ProcessName, Title=title.ToString(), Handle=h }); } catch {} return true; },IntPtr.Zero); return result; }
}
'@ }
function Normalize-WindowTitle { param([string]$Value) if ([string]::IsNullOrWhiteSpace($Value)) { return $null }; return $Value.Trim().Normalize([Text.NormalizationForm]::FormKC).ToUpperInvariant() }
function Get-TopLevelWindows { if ($env:QWEN_GIS_FOCUS_WINDOW_FIXTURE) { return @(ConvertFrom-Json -InputObject $env:QWEN_GIS_FOCUS_WINDOW_FIXTURE) }; return @([NativeWindow]::EnumerateTopLevelWindows()) }
$allowedNames = if ($Platform -eq 'qgis') { @('qgis-bin', 'qgis-ltr-bin', 'qgis') } else { @('knime', 'knime64') }
$windows = @(Get-TopLevelWindows | Where-Object { $allowedNames -contains $_.ProcessName })
if ($windows.Count -eq 0) { Write-FocusJson @{ status='not-running'; platform=$Platform }; exit 0 }
$target = $null
if ($null -ne $parsedTargetPid) { $matches=@($windows | Where-Object { $_.Pid -eq $parsedTargetPid }); if ($matches.Count -eq 1) { $target=$matches[0] } }
if ($null -eq $target -and $hasTitleHint) { $hint=Normalize-WindowTitle $TitleHint; $matches=@($windows | Where-Object { (Normalize-WindowTitle $_.Title) -eq $hint }); if ($matches.Count -eq 1) { $target=$matches[0] } }
if ($null -eq $target -and $hasTitleHint) {
    $hint=Normalize-WindowTitle $TitleHint
    $contains=@($windows | Where-Object {
        $title=Normalize-WindowTitle $_.Title
        $null -ne $title -and ($title.Contains($hint) -or $hint.Contains($title))
    })
    if ($contains.Count -eq 1) { $target=$contains[0] }
}
if ($null -eq $target -and $windows.Count -eq 1) { $target=$windows[0] }
if ($null -eq $target) { Write-FocusJson @{ status='ambiguous'; platform=$Platform; diagnostic='Multiple allowlisted top-level windows match without a decisive hint' }; exit 3 }
if ($env:QWEN_GIS_FOCUS_WINDOW_FIXTURE) { Write-FocusJson @{ status='focused'; platform=$Platform; pid=$target.Pid; title=$target.Title }; exit 0 }
try { [NativeWindow]::ShowWindowAsync($target.Handle,9)|Out-Null; if (-not [NativeWindow]::SetForegroundWindow($target.Handle)) { Write-FocusJson @{ status='error'; platform=$Platform; pid=$target.Pid; title=$target.Title; diagnostic='Windows denied foreground activation' }; exit 1 }; Write-FocusJson @{ status='focused'; platform=$Platform; pid=$target.Pid; title=$target.Title } } catch { Write-FocusJson @{ status='error'; platform=$Platform; diagnostic=$_.Exception.Message }; exit 1 }
