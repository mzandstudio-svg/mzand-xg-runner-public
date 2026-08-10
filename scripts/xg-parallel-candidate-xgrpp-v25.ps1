$ErrorActionPreference='Stop'
if(-not$env:POSITION_XGID){throw 'POSITION_XGID is required'}
$target=$env:POSITION_XGID.Trim()
if($target-notlike'XGID=*'){throw 'POSITION_XGID must start with XGID='}

$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-xgrpp-v21.ps1'
$src=Get-Content $srcPath -Raw

# Parameterize the development XGID used by the generated v21 runner.
$expectedOld=@'
$expectedPayload='-a---BDBBA--dBb--c-dBa----:1:-1:-1:64:6:16:0:19:10'
'@
$expectedOld=$expectedOld.Trim()
$expectedNew='$expectedPayload=$env:POSITION_XGID.Substring(5)'
if(-not$src.Contains($expectedOld)){throw 'v21 expected payload marker not found'}
$generated=$src.Replace($expectedOld,$expectedNew)

# A small fraction of fresh XG sessions accept the Analyze Position WM_COMMAND
# without opening a Save Game prompt but still leave the Move panel blank. The
# v21 loop only retried after a Save Game dialog or an XGID mismatch, so such a
# silently lost command timed out after 240 seconds. Reissue at bounded idle
# checkpoints while the process is responsive; valid analyses finish well before
# the first checkpoint, so active work is not repeatedly interrupted.
$initOld=@'
$baselineText='';$baseline=$null;$analysisReady=$false;$analysisElapsed=0
'@
$initNew=@'
$baselineText='';$baseline=$null;$analysisReady=$false;$analysisElapsed=0
$idleReissueSchedule=@(20,60,120)
$idleReissueIndex=0
$idleReissueCount=0
'@
if(-not$generated.Contains($initOld.Trim())){throw 'v21 analysis initialization marker not found'}
$generated=$generated.Replace($initOld.Trim(),$initNew.Trim())

$loopOld=@'
  if(-not$xg.Responding){continue}
  try{$candidateText=ExportText $xg}catch{continue}
'@
$loopNew=@'
  if(-not$xg.Responding){continue}
  if($idleReissueIndex-lt$idleReissueSchedule.Count -and $analysisElapsed-ge$idleReissueSchedule[$idleReissueIndex]){
    $idleReissueCount++
    ReissueMidgameAnalysis
    "ANALYZE_IDLE_REISSUED_AT_SECONDS: $analysisElapsed"|Out-File $report -Append
    Post "$prefix/analyze-idle-reissued" 'success' "Analyze Position reissued after idle wait ${analysisElapsed}s"
    $idleReissueIndex++
    Start-Sleep -Milliseconds 600
  }
  try{$candidateText=ExportText $xg}catch{continue}
'@
if(-not$generated.Contains($loopOld.Trim())){throw 'v21 responsive analysis loop marker not found'}
$generated=$generated.Replace($loopOld.Trim(),$loopNew.Trim())

$reportOld=@'
"ANALYZE_REISSUE_COUNT: $reissueCount"|Out-File $report -Append
'@
$reportNew=@'
"ANALYZE_REISSUE_COUNT: $reissueCount"|Out-File $report -Append
"ANALYZE_IDLE_REISSUE_COUNT: $idleReissueCount"|Out-File $report -Append
'@
if(-not$generated.Contains($reportOld.Trim())){throw 'v21 analysis reissue report marker not found'}
$generated=$generated.Replace($reportOld.Trim(),$reportNew.Trim())

$tmp=Join-Path $env:RUNNER_TEMP "xg-v25-xgrpp-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
