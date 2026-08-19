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

$root=[System.Windows.Automation.AutomationElement]::RootElement
function FindSaveGameDialog(){
  try{
    $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($w in $wins){
      try{if([string]$w.Current.Name-eq'Save Game'){return $w}}catch{}
    }
  }catch{}
  return $null
}
function DismissSaveGameNo(){
  $d=FindSaveGameDialog
  if($null-eq$d){return $false}
  try{
    $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')
    $b=$d.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cond)
    if($null-ne$b){
      $p=$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
      if($null-ne$p){$p.Invoke();Start-Sleep -Milliseconds 700;return $true}
    }
  }catch{}
  try{
    [V15S]::SetForegroundWindow([IntPtr]$d.Current.NativeWindowHandle)|Out-Null
    Start-Sleep -Milliseconds 150
    [System.Windows.Forms.SendKeys]::SendWait('%n')
    Start-Sleep -Milliseconds 700
    return $true
  }catch{}
  return $false
}

# A target paste can be intercepted by XG's unsaved-position prompt.  Handle that
# transition here, but do not attempt a focus-dependent Ctrl+C verification: the
# authoritative verification happens after Analyze, where the structured export
# includes the exact XGID and the workflow compares it byte-for-byte with MIDGAME_XGID.
$pasteSent=$false
for($attempt=1;$attempt-le4;$attempt++){
  $xg.Refresh()
  Set-Clipboard -Value $mid
  [V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  $pasteSent=$true
  Start-Sleep 1
  $dismissed=DismissSaveGameNo
  "SWITCH_ATTEMPT_${attempt}_SAVE_DISMISSED: $dismissed"|Out-File $report -Append
  if($dismissed){Start-Sleep -Milliseconds 700;continue}
  # Give FireMonkey a bounded interval to commit the paste before Analyze.
  Start-Sleep 2
  break
}

$xg.Refresh()
"MIDGAME_XGID_PASTE_SENT: $pasteSent"|Out-File $report -Append
"TITLE_AFTER_SWITCH: $($xg.MainWindowTitle)"|Out-File $report -Append
"XG_RESPONDING_AFTER_SWITCH: $($xg.Responding)"|Out-File $report -Append
if(-not$pasteSent){throw 'target XGID paste was not sent'}
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'target paste did not leave XG in Position.xgp'}
'MIDGAME_POSITION_READY_FOR_ANALYSIS: True'|Out-File $report -Append
