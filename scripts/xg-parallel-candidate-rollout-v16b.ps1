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

# Delphi exposes the prompt as a valid UIA window, but its edit/button controls are
# not consistently parented beneath that element. Search the full UIA tree and keep
# control matches scoped to this XG process.
$oldP=@'
$pdesc=$prompt.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
'@
$oldP=$oldP.Trim()
$newP=@'
$pdesc=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
'@
$newP=$newP.Trim()
if(-not $generated.Contains($oldP)){throw 'prompt descendant source pattern missing'}
$generated=$generated.Replace($oldP,$newP)

$oldOk=@'
if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'Ok'){$ok=$e}
'@
$oldOk=$oldOk.Trim()
$newOk=@'
if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'Ok'){$ok=$e}
'@
$newOk=$newOk.Trim()
if(-not $generated.Contains($oldOk)){throw 'Ok control source pattern missing'}
$generated=$generated.Replace($oldOk,$newOk)

$oldGames=@'
if($e.Current.Name-eq'1296' -and $e.Current.ClassName-eq'TSpinEditX'){$games1296=$true}
'@
$oldGames=$oldGames.Trim()
$newGames=@'
if($e.Current.ProcessId-eq$xg.Id -and $e.Current.Name-eq'1296'){$games1296=$true}
'@
$newGames=$newGames.Trim()
if(-not $generated.Contains($oldGames)){throw '1296 control source pattern missing'}
$generated=$generated.Replace($oldGames,$newGames)

$tmp=Join-Path $env:RUNNER_TEMP "xg-v16b-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
