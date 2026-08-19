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

# Loading a new XGID can be delayed by XG's unsaved-position Save Game prompt.
# Never trust the window title alone: after every paste, ask XG itself to copy the
# currently loaded position back. A sentinel prevents a blocked Ctrl+C from being
# mistaken for a successful load. Only an exact target-XGID echo opens the gate.
$loaded=$false
for($attempt=1;$attempt-le4 -and -not$loaded;$attempt++){
  $xg.Refresh()
  Set-Clipboard -Value $mid
  [V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  Start-Sleep 1

  $dismissed=DismissSaveGameNo
  "SWITCH_ATTEMPT_${attempt}_SAVE_DISMISSED: $dismissed"|Out-File $report -Append
  if($dismissed){Start-Sleep -Milliseconds 600;continue}

  $sentinel="__MZAND_XGID_VERIFY_${attempt}__"
  Set-Clipboard -Value $sentinel
  [V15S]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('^c')
  Start-Sleep -Milliseconds 800

  # Ctrl+C itself can surface a delayed Save Game dialog. If so, dismiss and retry.
  $dismissedAfterCopy=DismissSaveGameNo
  "SWITCH_ATTEMPT_${attempt}_SAVE_AFTER_COPY: $dismissedAfterCopy"|Out-File $report -Append
  if($dismissedAfterCopy){continue}

  $echo=''
  try{$echo=[string](Get-Clipboard -Raw)}catch{$echo=[string](Get-Clipboard)}
  $echo=$echo.Trim()
  "SWITCH_ATTEMPT_${attempt}_ECHO: $echo"|Out-File $report -Append
  $loaded=($echo-eq$mid)
  "SWITCH_ATTEMPT_${attempt}_EXACT_XGID: $loaded"|Out-File $report -Append
}

$xg.Refresh()
"TITLE_AFTER_SWITCH: $($xg.MainWindowTitle)"|Out-File $report -Append
"XG_RESPONDING_AFTER_SWITCH: $($xg.Responding)"|Out-File $report -Append
"MIDGAME_EXACT_XGID_VERIFIED: $loaded"|Out-File $report -Append
if(-not$loaded){throw 'target XGID was not verified after 4 bounded switch attempts'}
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'verified XGID did not load as Position.xgp'}
'MIDGAME_POSITION_READY_FOR_ANALYSIS: True'|Out-File $report -Append
