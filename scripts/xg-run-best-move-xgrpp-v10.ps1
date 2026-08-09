$ErrorActionPreference='Stop'
$src=Get-Content "$env:GITHUB_WORKSPACE\scripts\xg-run-position-analysis-v8.ps1" -Raw
$marker='Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue'
$idx=$src.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v8 cleanup marker missing'}
$prefix=$src.Substring(0,$idx)
$tail=@'

$xg.Refresh()
$hwnd=[IntPtr]$xg.MainWindowHandle
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V10N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function LeftClick([int]$x,[int]$y){[V10N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V10N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V10N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function RightClick([int]$x,[int]$y){[V10N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V10N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V10N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)}
$wr=New-Object V10N+RECT
if(-not[V10N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$report10="$env:GITHUB_WORKSPACE\xg-v10-report.txt"
"MAIN_RECT: $($wr.Left),$($wr.Top),$($wr.Right),$($wr.Bottom)"|Out-File $report10
'BASE_ANALYZE_LEVEL: World Class'|Out-File $report10 -Append

# Evidence from v9: best row context point is main+(130,364), XG Roller++ row center is main+(230,448).
$bestX=$wr.Left+130;$bestY=$wr.Top+364
[V10N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
RightClick $bestX $bestY
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v10-context-before-xgrpp.png"
$xgrX=$wr.Left+230;$xgrY=$wr.Top+448
"XGRPP_CLICK_POINT: $xgrX,$xgrY"|Out-File $report10 -Append
LeftClick $xgrX $xgrY
'XGRPP_COMMAND_CLICKED: True'|Out-File $report10 -Append
'ROLLOUT_MENU_COMMAND_CLICKED: False'|Out-File $report10 -Append
Post 'xg-public-v10/xgrpp-started' 'success' 'XG Roller++ menu row clicked for best move'

Start-Sleep 2
Shot "$env:GITHUB_WORKSPACE\xg-v10-xgrpp-2s.png"
Start-Sleep 18
Shot "$env:GITHUB_WORKSPACE\xg-v10-xgrpp-20s.png"
Start-Sleep 40
Shot "$env:GITHUB_WORKSPACE\xg-v10-xgrpp-60s.png"
Start-Sleep 60
Shot "$env:GITHUB_WORKSPACE\xg-v10-xgrpp-120s.png"
$xg.Refresh()
"XG_RESPONDING_120S: $($xg.Responding)"|Out-File $report10 -Append
"TITLE_120S: $($xg.MainWindowTitle)"|Out-File $report10 -Append
'XGRPP_RESULT_CAPTURED: True'|Out-File $report10 -Append
Post 'xg-public-v10/xgrpp-captured' 'success' 'XG Roller++ result screenshots captured through 120s'
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$generated=Join-Path $env:RUNNER_TEMP 'xg-v10-generated.ps1'
Set-Content $generated ($prefix+$tail) -Encoding UTF8
& $generated
