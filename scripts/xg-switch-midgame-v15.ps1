$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
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
$mid=if($env:MZAND_XGID){$env:MZAND_XGID}else{'XGID=-a----EaCA--eD---a-cbA--bA:0:0:1:33:0:0:0:5:10'}
$report="$env:GITHUB_WORKSPACE\xg-v15-switch-report.txt"
"MIDGAME_XGID: $mid"|Out-File $report
"TITLE_BEFORE_SWITCH: $before"|Out-File $report -Append
Set-Clipboard -Value $mid
Start-Sleep -Milliseconds 300
$clip=(Get-Clipboard -Raw).Trim()
if($clip-ne$mid){throw 'midgame clipboard verification failed'}
[V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('^v')

$root=[System.Windows.Automation.AutomationElement]::RootElement
$saveWin=$null
for($i=0;$i-lt48 -and $null-eq$saveWin;$i++){
  $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($w in $wins){
    try{if($w.Current.ProcessId-eq$xg.Id -and $w.Current.Name-eq'Save Game'){$saveWin=$w;break}}catch{}
  }
  if($null-eq$saveWin){Start-Sleep -Milliseconds 250}
}
if($null-ne$saveWin){
  $noButton=$saveWin.FindFirst([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')))
  if($null-eq$noButton){throw 'Save Game dialog found but No button missing'}
  $invoke=$noButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $invoke.Invoke()
  'SAVE_GAME_DIALOG_FOUND: True'|Out-File $report -Append
  'SAVE_GAME_NO_CLICKED: True'|Out-File $report -Append
}else{
  'SAVE_GAME_DIALOG_FOUND: False'|Out-File $report -Append
  'SAVE_GAME_NO_CLICKED: False'|Out-File $report -Append
}
Start-Sleep 2

# The first Ctrl+V can be consumed by the unsaved-position transition. Reissue the exact
# target XGID after that transition settles; the following Analyze+export step is the
# authoritative verification that the intended non-book position was loaded.
Set-Clipboard -Value $mid
$xg.Refresh()
[V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('^v')
'MIDGAME_XGID_REPASTE_SENT: True'|Out-File $report -Append
Start-Sleep 8

$xg.Refresh()
"TITLE_AFTER_SWITCH: $($xg.MainWindowTitle)"|Out-File $report -Append
"XG_RESPONDING_AFTER_SWITCH: $($xg.Responding)"|Out-File $report -Append
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'midgame XGID did not load as Position.xgp'}
'MIDGAME_POSITION_READY_FOR_ANALYSIS: True'|Out-File $report -Append
