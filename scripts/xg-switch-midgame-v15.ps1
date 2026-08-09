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
$mid='XGID=-a---BDBBA--dBb--c-dBa----:1:-1:-1:64:6:16:0:19:10'
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
Start-Sleep 6

$xg.Refresh()
[V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 300
$sentinel='__MZAND_SWITCH_VERIFY__'
Set-Clipboard -Value $sentinel
[System.Windows.Forms.SendKeys]::SendWait('^c')
Start-Sleep 1
try{$current=[string](Get-Clipboard -Raw -TextFormatType Text)}catch{$current=[string](Get-Clipboard -Raw)}
$current=$current.Trim()
"CLIPBOARD_CHANGED_AFTER_COPY: $($current-ne$sentinel)"|Out-File $report -Append
if($current-eq$sentinel){throw 'midgame switch verification copy was blocked'}
$m=[regex]::Match($current,'(?m)^XGID=[^\r\n]+')
$currentXgid=$(if($m.Success){$m.Value.Trim()}else{''})
"TITLE_AFTER_SWITCH: $($xg.MainWindowTitle)"|Out-File $report -Append
"XG_RESPONDING_AFTER_SWITCH: $($xg.Responding)"|Out-File $report -Append
"CURRENT_XGID_AFTER_SWITCH: $currentXgid"|Out-File $report -Append
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'midgame XGID did not load as Position.xgp'}
if($currentXgid-ne$mid){throw "midgame XGID verification failed: [$currentXgid]"}
'MIDGAME_POSITION_READY: True'|Out-File $report -Append
