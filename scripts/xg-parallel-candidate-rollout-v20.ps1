# v20: adaptive rollout depth wrapper for 1296 or 5184 games
$ErrorActionPreference='Stop'
$requestedGames=if($env:ROLLOUT_GAMES){[int]$env:ROLLOUT_GAMES}else{1296}
if($requestedGames-notin@(1296,5184)){throw "ROLLOUT_GAMES must be 1296 or 5184, got $requestedGames"}
$env:ROLLOUT_GAMES=[string]$requestedGames

$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-rollout-v19.ps1'
$src=Get-Content $srcPath -Raw

$tailOld=@'
$tmp=Join-Path $env:RUNNER_TEMP "xg-v19-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
'@
$tailNew=@'
$requestedGames=[int]$env:ROLLOUT_GAMES
if($requestedGames-notin@(1296,5184)){throw "ROLLOUT_GAMES must be 1296 or 5184, got $requestedGames"}
if($requestedGames-ne1296){
  $gameText=[string]$requestedGames
  $gameControlMarker='Shot "$prefix-before-ok"'
  $gameControlBlock=@'
$pdesc=$prompt.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$gameSpins=@()
foreach($e in $pdesc){try{if($e.Current.ClassName-eq'TSpinEditX'){$gameSpins+=,$e}}catch{}}
if($gameSpins.Count-ne1){Shot "$prefix-games-control-mismatch";throw "Expected one rollout games control, got $($gameSpins.Count)"}
$gameSpin=$gameSpins[0]
$gameSet=$false
try{
  $valuePattern=[System.Windows.Automation.ValuePattern]$gameSpin.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  $valuePattern.SetValue('__GAMES__')
  $gameSet=$true
}catch{}
if(-not$gameSet){
  $gr=$gameSpin.Current.BoundingRectangle
  LeftClick ([int]($gr.X+$gr.Width/2)) ([int]($gr.Y+$gr.Height/2))
  Start-Sleep -Milliseconds 150
  [System.Windows.Forms.SendKeys]::SendWait('^a')
  Start-Sleep -Milliseconds 100
  [System.Windows.Forms.SendKeys]::SendWait('__GAMES__')
}
Start-Sleep -Milliseconds 400
$pdesc=$prompt.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$gameVerified=$false
foreach($e in $pdesc){try{if($e.Current.ClassName-eq'TSpinEditX' -and $e.Current.Name-eq'__GAMES__'){$gameVerified=$true}}catch{}}
if(-not$gameVerified){Shot "$prefix-games-not-configured";throw 'Rollout games control did not update to __GAMES__'}
"ROLLOUT_GAMES_CONFIGURED: __GAMES__"|Out-File $report -Append
'@
  $gameControlBlock=$gameControlBlock.Replace('__GAMES__',$gameText)
  if(-not$generated.Contains($gameControlMarker)){throw 'Rollout prompt OK marker not found for adaptive depth'}
  $generated=$generated.Replace($gameControlMarker,$gameControlBlock+$gameControlMarker)

  # The generated v16/v19 script has a single hard-coded depth contract. After
  # configuring the prompt control, rewrite completion provenance, record metadata,
  # status text and diagnostics to the requested deeper rollout count.
  $generated=$generated.Replace('1296',$gameText)
  $generated=$generated.Replace('1200','3600')
}
$tmp=Join-Path $env:RUNNER_TEMP "xg-v20-candidate-$env:CANDIDATE_RANK-$requestedGames.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
'@
if(-not$src.Contains($tailOld)){throw 'v19 execution tail not found'}
$generatedWrapper=$src.Replace($tailOld,$tailNew)
$tmpWrapper=Join-Path $env:RUNNER_TEMP "xg-v20-wrapper-$env:CANDIDATE_RANK-$requestedGames.ps1"
Set-Content $tmpWrapper $generatedWrapper -Encoding UTF8
& $tmpWrapper
