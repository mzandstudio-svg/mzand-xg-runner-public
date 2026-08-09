$ErrorActionPreference='Stop'
$src=Get-Content "$env:GITHUB_WORKSPACE\scripts\xg-run-position-analysis-v8.ps1" -Raw
$marker='Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue'
$idx=$src.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v8 cleanup marker missing'}
$prefix=$src.Substring(0,$idx)
$tail=@'

# The v8 controlled analysis is complete and the candidate list is visible.
$xg.Refresh()
$hwnd=[IntPtr]$xg.MainWindowHandle
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V9N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
$wr=New-Object V9N+RECT
if(-not[V9N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
# Evidence from v8 screenshot: first candidate row center is at screen ~180,414 when main is 50,50.
$cx=$wr.Left+130
$cy=$wr.Top+364
"BEST_MOVE_CONTEXT_POINT: $cx,$cy"|Out-File "$env:GITHUB_WORKSPACE\xg-v9-report.txt"
[V9N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
[V9N]::SetCursorPos($cx,$cy)|Out-Null
Start-Sleep -Milliseconds 150
[V9N]::mouse_event(8,0,0,0,[UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
[V9N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v9-best-move-context.png"
'BEST_MOVE_RIGHT_CLICKED: True'|Out-File "$env:GITHUB_WORKSPACE\xg-v9-report.txt" -Append
'XGRPP_STARTED: False'|Out-File "$env:GITHUB_WORKSPACE\xg-v9-report.txt" -Append
'ROLLOUT_STARTED: False'|Out-File "$env:GITHUB_WORKSPACE\xg-v9-report.txt" -Append
Post 'xg-public-v9/context-captured' 'success' 'Best move context menu screenshot captured'
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$generated=Join-Path $env:RUNNER_TEMP 'xg-v9-generated.ps1'
Set-Content $generated ($prefix+$tail) -Encoding UTF8
& $generated
