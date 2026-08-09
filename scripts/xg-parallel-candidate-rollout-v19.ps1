$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-rollout-v16.ps1'
$src=Get-Content $srcPath -Raw

# Non-book XGID imports can retain an unsaved game shell. Analyze -> Position then
# raises a modal Save Game prompt. Dismiss it explicitly with No before waiting for
# analyzed-candidate export. Opening-book Position.xgp controls do not always show it.
$oldAnalysis=@'
Start-Sleep 15
Post "$prefix/analyzed" 'success' 'Analyze Position completed for candidate selection'

$baselineText=ExportText $xg
$baseline=ParseExport $baselineText "$prefix-baseline"
'@
$newAnalysis=@'
$root=[System.Windows.Automation.AutomationElement]::RootElement
$savePromptSeen=$false
$savePromptDismissed=$false
for($saveWait=0;$saveWait-lt20;$saveWait++){
  Start-Sleep -Milliseconds 500
  $allUi=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $saveDialogs=@()
  foreach($e in $allUi){
    try{
      if($e.Current.ProcessId-eq$xg.Id -and $e.Current.Name-eq'Save Game' -and -not$e.Current.IsOffscreen){$saveDialogs+=,$e}
    }catch{}
  }
  if($saveDialogs.Count-gt1){Shot "$prefix-save-prompt-ambiguous";throw "Expected at most one Save Game dialog, got $($saveDialogs.Count)"}
  if($saveDialogs.Count-eq1){
    $savePromptSeen=$true
    $dlg=$saveDialogs[0]
    $children=$dlg.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    $noButtons=@()
    foreach($e in $children){
      try{
        if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'No' -and $e.Current.IsEnabled){$noButtons+=,$e}
      }catch{}
    }
    if($noButtons.Count-ne1){Shot "$prefix-save-prompt-no-mismatch";throw "Expected one enabled No button in Save Game dialog, got $($noButtons.Count)"}
    $nr=$noButtons[0].Current.BoundingRectangle
    Shot "$prefix-save-prompt-before-no"
    LeftClick ([int]($nr.X+$nr.Width/2)) ([int]($nr.Y+$nr.Height/2))
    $savePromptDismissed=$true
    "SAVE_GAME_PROMPT_NO_CLICKED: True"|Out-File $report -Append
    Post "$prefix/save-prompt" 'success' 'Unsaved-game Save Game prompt dismissed with No'
    Start-Sleep -Milliseconds 700
    break
  }
}
"SAVE_GAME_PROMPT_SEEN: $savePromptSeen"|Out-File $report -Append
"SAVE_GAME_PROMPT_DISMISSED: $savePromptDismissed"|Out-File $report -Append

$baselineText=''
$analysisReady=$false
$analysisElapsed=0
while($analysisElapsed-lt240 -and -not$analysisReady){
  Start-Sleep 5
  $analysisElapsed+=5
  $xg.Refresh()
  if($xg.HasExited){throw 'XG exited during Analyze Position'}
  if(-not$xg.Responding){continue}
  try{$candidateText=ExportText $xg}catch{continue}
  if($candidateText.Length-gt100 -and $candidateText-match'(?m)^\s*1\.' -and $candidateText-match'(?i)eq:[+-]\d+\.\d+'){
    $baselineText=$candidateText
    $analysisReady=$true
  }
}
if(-not$analysisReady){
  Shot "$prefix-analysis-timeout"
  throw "Analyze Position export did not become ready within ${analysisElapsed}s"
}
"ANALYSIS_READY_SECONDS: $analysisElapsed"|Out-File $report -Append
Post "$prefix/analyzed" 'success' "Analyze Position export ready after ${analysisElapsed}s"
$baseline=ParseExport $baselineText "$prefix-baseline"
'@
if(-not$src.Contains($oldAnalysis)){throw 'fixed Analyze Position block not found'}
$generated=$src.Replace($oldAnalysis,$newAnalysis)

# Apply the stable rollout submenu/prompt fixes from v16b.
$start=$generated.IndexOf('$sub=$subs[0]',[System.StringComparison]::Ordinal)
if($start-lt0){throw 'v16 preset block start not found'}
$tailMarker='$prompt=$null'
$tail=$generated.IndexOf($tailMarker,$start,[System.StringComparison]::Ordinal)
if($tail-lt0){throw 'v16 prompt block marker not found'}
$newBlock=@'
$sub=$subs[0]
$sr=$sub.Current.BoundingRectangle
"ROLLOUT_SUBMENU_RECT: $($sr.X),$($sr.Y),$($sr.Width),$($sr.Height)"|Out-File $report -Append
$presetX=[int]($sr.X+$sr.Width/2)
$presetY=[int]($sr.Y+62)
"PRESET_GEOMETRY_CLICK: $presetX,$presetY"|Out-File $report -Append
LeftClick $presetX $presetY
Start-Sleep 1

'@
$generated=$generated.Substring(0,$start)+$newBlock+$generated.Substring($tail)
$generated=$generated.Replace('function FindRolloutPrompt([int]$pid){','function FindRolloutPrompt([int]$processId){')
$generated=$generated.Replace('ProcessId-eq$pid','ProcessId-eq$processId')

$controlsStart=$generated.IndexOf('$pdesc=$prompt.FindAll(',[System.StringComparison]::Ordinal)
if($controlsStart-lt0){throw 'prompt controls block start not found'}
$controlsEnd=$generated.IndexOf('Post "$prefix/started"',$controlsStart,[System.StringComparison]::Ordinal)
if($controlsEnd-lt0){throw 'prompt controls block end not found'}
$promptAction=@'
$promptRect=$prompt.Current.BoundingRectangle
"PROMPT_RECT: $($promptRect.X),$($promptRect.Y),$($promptRect.Width),$($promptRect.Height)"|Out-File $report -Append
if($promptRect.Width-lt280 -or $promptRect.Width-gt340 -or $promptRect.Height-lt115 -or $promptRect.Height-gt160){
  Shot "$prefix-prompt-geometry-invalid"
  throw "Unexpected Rollout prompt geometry $($promptRect.Width)x$($promptRect.Height)"
}
Shot "$prefix-before-ok"
$okX=[int]($promptRect.X+($promptRect.Width*0.30))
$okY=[int]($promptRect.Y+($promptRect.Height*0.81))
"OK_GEOMETRY_CLICK: $okX,$okY"|Out-File $report -Append
LeftClick $okX $okY

'@
$generated=$generated.Substring(0,$controlsStart)+$promptAction+$generated.Substring($controlsEnd)

$tmp=Join-Path $env:RUNNER_TEMP "xg-v19-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
