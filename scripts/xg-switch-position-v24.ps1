$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V24S {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@

if(-not$env:POSITION_ID){throw 'POSITION_ID is required'}
if(-not$env:POSITION_XGID){throw 'POSITION_XGID is required'}
$positionId=$env:POSITION_ID
$target=$env:POSITION_XGID.Trim()
if($target-notlike'XGID=*'){throw 'POSITION_XGID must start with XGID='}

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
$before=$xg.MainWindowTitle
Set-Clipboard -Value $target
Start-Sleep -Milliseconds 300
$clip=(Get-Clipboard -Raw).Trim()
if($clip-ne$target){throw 'target XGID clipboard verification failed'}
[V24S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep 8
$xg.Refresh()
$report="$env:GITHUB_WORKSPACE\xg-v24-switch-$positionId-report.txt"
"POSITION_ID: $positionId"|Out-File $report
"POSITION_XGID: $target"|Out-File $report -Append
'SCOPE: non-pristine development position'|Out-File $report -Append
"TITLE_BEFORE_SWITCH: $before"|Out-File $report -Append
"TITLE_AFTER_SWITCH: $($xg.MainWindowTitle)"|Out-File $report -Append
"XG_RESPONDING_AFTER_SWITCH: $($xg.Responding)"|Out-File $report -Append
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'target XGID did not load as Position.xgp'}
'POSITION_READY: True'|Out-File $report -Append
