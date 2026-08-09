$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-xgrpp-v18.ps1'
$src=Get-Content $srcPath -Raw

$old=@'
Start-Sleep 15
$baselineText=ExportText $xg
$baseline=ParseExport $baselineText "$prefix-baseline"
'@
$new=@'
$root=[System.Windows.Automation.AutomationElement]::RootElement
$savePromptSeen=$false
$savePromptDismissed=$false
for($saveWait=0;$saveWait-lt20;$saveWait++){
  Start-Sleep -Milliseconds 500
  $allUi=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $saveDialogs=@()
  foreach($e in $allUi){try{if($e.Current.ProcessId-eq$xg.Id -and $e.Current.Name-eq'Save Game' -and -not$e.Current.IsOffscreen){$saveDialogs+=,$e}}catch{}}
  if($saveDialogs.Count-gt1){Shot "$prefix-save-prompt-ambiguous";throw "Expected at most one Save Game dialog, got $($saveDialogs.Count)"}
  if($saveDialogs.Count-eq1){
    $savePromptSeen=$true
    $dlg=$saveDialogs[0]
    $dr=$dlg.Current.BoundingRectangle
    if($dr.Width-lt330 -or $dr.Width-gt390 -or $dr.Height-lt120 -or $dr.Height-gt170){Shot "$prefix-save-prompt-geometry-invalid";throw "Unexpected Save Game dialog geometry $($dr.Width)x$($dr.Height)"}
    $noX=[int]($dr.X+($dr.Width*0.66));$noY=[int]($dr.Y+($dr.Height*0.85))
    Shot "$prefix-save-prompt-before-no"
    LeftClick $noX $noY
    $savePromptDismissed=$true
    Start-Sleep -Milliseconds 700
    break
  }
}
"SAVE_GAME_PROMPT_SEEN: $savePromptSeen"|Out-File $report -Append
"SAVE_GAME_PROMPT_DISMISSED: $savePromptDismissed"|Out-File $report -Append
if($savePromptDismissed){
  $main=[V18N]::GetMenu($hwnd);$analyze=[V18N]::GetSubMenu($main,4);$positionId=[V18N]::GetMenuItemID($analyze,1)
  [V18N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
  [void][V18N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
  "ANALYZE_REISSUED_AFTER_SAVE_PROMPT: True"|Out-File $report -Append
}
$baselineText='';$analysisReady=$false;$analysisElapsed=0
while($analysisElapsed-lt240 -and -not$analysisReady){
  Start-Sleep 5;$analysisElapsed+=5;$xg.Refresh()
  if($xg.HasExited){throw 'XG exited during Analyze Position'}
  if(-not$xg.Responding){continue}
  try{$candidateText=ExportText $xg}catch{continue}
  if($candidateText.Length-gt100 -and $candidateText-match'(?m)^\s*1\.' -and $candidateText-match'(?i)eq:[+-]\d+\.\d+'){$baselineText=$candidateText;$analysisReady=$true}
}
if(-not$analysisReady){Shot "$prefix-analysis-timeout";throw "Analyze Position export did not become ready within ${analysisElapsed}s"}
"ANALYSIS_READY_SECONDS: $analysisElapsed"|Out-File $report -Append
$baseline=ParseExport $baselineText "$prefix-baseline"
'@
if(-not$src.Contains($old)){throw 'v18 fixed Analyze Position block not found'}
$generated=$src.Replace($old,$new)
$tmp=Join-Path $env:RUNNER_TEMP "xg-v21-xgrpp-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
