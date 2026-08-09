$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-rollout-v16.ps1'
$src=Get-Content $srcPath -Raw
$start=$src.IndexOf('$sub=$subs[0]',[System.StringComparison]::Ordinal)
if($start-lt0){throw 'v16 preset block start not found'}
$tailMarker='$prompt=$null'
$tail=$src.IndexOf($tailMarker,$start,[System.StringComparison]::Ordinal)
if($tail-lt0){throw 'v16 prompt block marker not found'}
$newBlock=@'
$sub=$subs[0]
$sr=$sub.Current.BoundingRectangle
"ROLLOUT_SUBMENU_RECT: $($sr.X),$($sr.Y),$($sr.Width),$($sr.Height)"|Out-File $report -Append
# Single-selection changes UIAutomation item ids. The verified prompt screenshot
# shows this geometry selects: Moves 3-ply, cube decisions XG Roller.
$presetX=[int]($sr.X+$sr.Width/2)
$presetY=[int]($sr.Y+62)
"PRESET_GEOMETRY_CLICK: $presetX,$presetY"|Out-File $report -Append
LeftClick $presetX $presetY
Start-Sleep 1

'@
$generated=$src.Substring(0,$start)+$newBlock+$src.Substring($tail)

# PowerShell variable names are case-insensitive; $PID is a reserved read-only variable.
$generated=$generated.Replace('function FindRolloutPrompt([int]$pid){','function FindRolloutPrompt([int]$processId){')
$generated=$generated.Replace('ProcessId-eq$pid','ProcessId-eq$processId')

# Delphi's child-control UIA parenting is unstable, while the Rollout prompt itself
# is stable. v16 evidence shows the exact prompt text/preset and 1296 games. Validate
# the prompt rectangle, capture evidence, and click the relative center of its OK button.
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

$tmp=Join-Path $env:RUNNER_TEMP "xg-v16b-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
