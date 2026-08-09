$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-rollout-v16.ps1'
$src=Get-Content $srcPath -Raw

# Non-book positions can take materially longer than opening-book positions to finish
# Analyze Position. Replace the fixed 15-second assumption with export-based readiness.
$oldAnalysis=@'
Start-Sleep 15
Post "$prefix/analyzed" 'success' 'Analyze Position completed for candidate selection'

$baselineText=ExportText $xg
$baseline=ParseExport $baselineText "$prefix-baseline"
'@
$newAnalysis=@'
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
