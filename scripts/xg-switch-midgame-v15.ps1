$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V15S {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
$before=$xg.MainWindowTitle
$mid='XGID=-a---BDBBA--dBb--c-dBa----:1:-1:-1:64:6:16:0:19:10'
Set-Clipboard -Value $mid
Start-Sleep -Milliseconds 300
$clip=(Get-Clipboard -Raw).Trim()
if($clip-ne$mid){throw 'midgame clipboard verification failed'}
[V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep 8
$xg.Refresh()
$report="$env:GITHUB_WORKSPACE\xg-v15-switch-report.txt"
"MIDGAME_XGID: $mid"|Out-File $report
"TITLE_BEFORE_SWITCH: $before"|Out-File $report -Append
"TITLE_AFTER_SWITCH: $($xg.MainWindowTitle)"|Out-File $report -Append
"XG_RESPONDING_AFTER_SWITCH: $($xg.Responding)"|Out-File $report -Append
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'midgame XGID did not load as Position.xgp'}
'MIDGAME_POSITION_READY: True'|Out-File $report -Append
