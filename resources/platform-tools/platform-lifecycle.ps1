[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RawArguments
)

$ErrorActionPreference = 'Stop'

function Write-LifecycleJson { param([hashtable]$Value) [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress)) }

$Platform = $null
$Action = $null
$rawPid = $null
for ($index = 0; $index -lt $RawArguments.Count; $index += 2) {
    if ($index + 1 -ge $RawArguments.Count) { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic='Unsupported argument' }; exit 2 }
    $name = [string]$RawArguments[$index]
    $value = [string]$RawArguments[$index + 1]
    if ($name -eq '-Platform' -and $null -eq $Platform) { $Platform = $value }
    elseif ($name -eq '-Action' -and $null -eq $Action) { $Action = $value }
    elseif ($name -eq '-Pid' -and $null -eq $rawPid) { $rawPid = $value }
    else { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic='Unsupported argument' }; exit 2 }
}

if ($Platform -notin @('qgis', 'knime')) { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic='Unsupported platform' }; exit 2 }
if ($Action -notin @('status', 'start', 'focus', 'close')) { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic='Unsupported lifecycle action' }; exit 2 }

$targetPid = $null
if ($null -ne $rawPid) {
    [long]$candidatePid = 0
    if ([string]::IsNullOrWhiteSpace($rawPid) -or -not [long]::TryParse($rawPid, [ref]$candidatePid) -or $candidatePid -lt 1) {
        Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic='Pid must be a positive integer' }
        exit 2
    }
    $targetPid = $candidatePid
}

if (-not ('LifecycleWindow' -as [type])) {
    Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Diagnostics; using System.Runtime.InteropServices; using System.Text;
public sealed class LifecycleWindowInfo { public long Pid; public string ProcessName; public string Title; public IntPtr Handle; }
public static class LifecycleWindow {
 private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
 [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
 [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hWnd);
 [DllImport("user32.dll")] private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
 [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
 public static List<LifecycleWindowInfo> EnumerateTopLevelWindows() { var result=new List<LifecycleWindowInfo>(); EnumWindows((h,l)=>{ if(!IsWindowVisible(h))return true; var title=new StringBuilder(512); if(GetWindowText(h,title,title.Capacity)==0)return true; uint pid; GetWindowThreadProcessId(h,out pid); try { var p=Process.GetProcessById((int)pid); result.Add(new LifecycleWindowInfo { Pid=pid, ProcessName=p.ProcessName, Title=title.ToString(), Handle=h }); } catch {} return true; },IntPtr.Zero); return result; }
}
'@
}

function Get-TopLevelWindows {
    if ($env:QWEN_GIS_PLATFORM_LIFECYCLE_FIXTURE) { return @(ConvertFrom-Json -InputObject $env:QWEN_GIS_PLATFORM_LIFECYCLE_FIXTURE) }
    return @([LifecycleWindow]::EnumerateTopLevelWindows())
}

$allowedProcessNames = if ($Platform -eq 'qgis') { @('qgis-bin', 'qgis-ltr-bin', 'qgis') } else { @('knime', 'knime64') }
$allowedExecutableNames = if ($Platform -eq 'qgis') { @('qgis-bin.exe', 'qgis-ltr-bin.exe', 'qgis.exe') } else { @('knime.exe', 'knime64.exe') }
$windows = @(Get-TopLevelWindows | Where-Object { $allowedProcessNames -contains $_.ProcessName })

function Select-Window {
    if ($windows.Count -eq 0) { return $null }
    if ($null -ne $targetPid) {
        $matches = @($windows | Where-Object { $_.Pid -eq $targetPid })
        if ($matches.Count -eq 1) { return $matches[0] }
    }
    if ($windows.Count -eq 1) { return $windows[0] }
    return $null
}

if ($Action -eq 'start') {
    if ($windows.Count -gt 0) { Write-LifecycleJson @{ status='already-running'; platform=$Platform; action=$Action }; exit 0 }
    $executable = $null
    foreach ($name in $allowedExecutableNames) {
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue
        if ($command -and $allowedExecutableNames -contains [IO.Path]::GetFileName($command.Source)) { $executable = $command.Source; break }
    }
    if ($null -eq $executable) { Write-LifecycleJson @{ status='unavailable'; platform=$Platform; action=$Action; diagnostic='Allowlisted executable was not found' }; exit 0 }
    try {
        $started = Start-Process -FilePath $executable -PassThru
        Write-LifecycleJson @{ status='start-requested'; platform=$Platform; action=$Action; pid=$started.Id }
        exit 0
    } catch { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic=$_.Exception.Message }; exit 1 }
}

if ($windows.Count -eq 0) { Write-LifecycleJson @{ status='not-running'; platform=$Platform; action=$Action }; exit 0 }
$selected = Select-Window
if ($null -eq $selected) { Write-LifecycleJson @{ status='ambiguous'; platform=$Platform; action=$Action; diagnostic='Multiple allowlisted top-level windows match without a decisive pid' }; exit 3 }

if ($Action -eq 'status') { Write-LifecycleJson @{ status='running'; platform=$Platform; action=$Action; pid=$selected.Pid }; exit 0 }
if ($Action -eq 'focus') {
    try {
        [LifecycleWindow]::ShowWindowAsync($selected.Handle, 9) | Out-Null
        if (-not [LifecycleWindow]::SetForegroundWindow($selected.Handle)) { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; pid=$selected.Pid; diagnostic='Windows denied foreground activation' }; exit 1 }
        Write-LifecycleJson @{ status='focused'; platform=$Platform; action=$Action; pid=$selected.Pid }
        exit 0
    } catch { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic=$_.Exception.Message }; exit 1 }
}

try {
    if (-not [LifecycleWindow]::PostMessage($selected.Handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)) { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; pid=$selected.Pid; diagnostic='Windows denied the close request' }; exit 1 }
    Write-LifecycleJson @{ status='close-requested'; platform=$Platform; action=$Action; pid=$selected.Pid }
    exit 0
} catch { Write-LifecycleJson @{ status='error'; platform=$Platform; action=$Action; diagnostic=$_.Exception.Message }; exit 1 }
