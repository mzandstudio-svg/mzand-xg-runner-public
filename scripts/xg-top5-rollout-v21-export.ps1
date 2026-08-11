$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-top5-rollout-run.ps1'
$src=Get-Content $srcPath -Raw

# Give a genuine five-move 1296 rollout enough wall time on a 4-core hosted runner.
# v19 incorrectly exported after 1200 seconds even when the XG process was still
# continuously CPU-active. v21 treats timeout as incomplete evidence, never success.
$src=$src.Replace('while($elapsed-lt1200){','while($elapsed-lt3300){')
$src=$src.Replace("CPU_IDLE_COMPLETION_NOT_OBSERVED_WITHIN_1200S: True","CPU_IDLE_COMPLETION_NOT_OBSERVED_WITHIN_3300S: True")

$old=@'
'FINAL_ROLLOUT_EVIDENCE_CAPTURED: True'|Out-File $report -Append
Post 'xg-top5-v11/final-evidence' 'success' "Final rollout evidence captured at elapsed=$elapsed idleStreak=$idleStreak"
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$new=@'
if($idleStreak-lt3){
  'FINAL_ROLLOUT_EVIDENCE_CAPTURED: False'|Out-File $report -Append
  'CURRENT_1296_ROLLOUT_COMPLETION_VERIFIED: False'|Out-File $report -Append
  Post 'xg-top5-v21/final-evidence' 'failure' "Fresh 1296 rollout completion not observed by elapsed=$elapsed; export suppressed"
  Get-Content $report
  throw "Fresh XG 1296 rollout did not complete within the bounded wait ($elapsed seconds)"
}
'FINAL_ROLLOUT_EVIDENCE_CAPTURED: True'|Out-File $report -Append
'CURRENT_1296_ROLLOUT_COMPLETION_VERIFIED: True'|Out-File $report -Append
Post 'xg-top5-v21/final-evidence' 'success' "Fresh 1296 rollout completion observed at elapsed=$elapsed idleStreak=$idleStreak"

# Export only after verified completion. Historical Book rows are explicitly rejected:
# their footnotes may mention old rollouts, but they are not current-run provenance.
$script:xg.Refresh()
[R11N]::SetForegroundWindow([IntPtr]$script:xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 350
[System.Windows.Forms.SendKeys]::SendWait('^c')
Start-Sleep 1
try{$text=[string](Get-Clipboard -Raw -TextFormatType Text)}catch{$text=[string](Get-Clipboard -Raw)}
$export="$env:GITHUB_WORKSPACE\xg-top5-v21-export.txt"
Set-Content $export $text -Encoding UTF8
"FINAL_EXPORT_LENGTH: $($text.Length)"|Out-File $report -Append
if($text.Length-lt100){throw "Final XG rollout export too short: $($text.Length)"}
$matches=[regex]::Matches($text,'(?m)^\s*\d+\.\s+(.+?)\s+eq:([+-]\d+\.\d+)')
"FINAL_EXPORT_CANDIDATE_ROWS: $($matches.Count)"|Out-File $report -Append
if($matches.Count-ne5){throw "Expected exactly 5 candidate equity rows after top-five rollout, got $($matches.Count)"}
$bookRows=[regex]::Matches($text,'(?mi)^\s*\d+\.\s+Book[⁰¹²³⁴⁵⁶⁷⁸⁹]*\s+')
"FINAL_EXPORT_BOOK_ROWS: $($bookRows.Count)"|Out-File $report -Append
if($bookRows.Count-gt0){
  'FRESH_ROLLOUT_PROVENANCE: False'|Out-File $report -Append
  throw "Historical Book rows remain after reported rollout completion; refusing stale provenance"
}
$rolloutRows=[regex]::Matches($text,'(?mi)^\s*\d+\.\s+Rollout[⁰¹²³⁴⁵⁶⁷⁸⁹]*\s+')
"FINAL_EXPORT_EXPLICIT_ROLLOUT_ROWS: $($rolloutRows.Count)"|Out-File $report -Append
if($rolloutRows.Count-ne5){
  'FRESH_ROLLOUT_PROVENANCE: False'|Out-File $report -Append
  throw "Expected 5 explicit Rollout source rows, got $($rolloutRows.Count)"
}
'FRESH_ROLLOUT_PROVENANCE: True'|Out-File $report -Append
for($i=0;$i-lt[math]::Min(5,$matches.Count);$i++){
  "PARSED_$($i+1)_MOVE: $($matches[$i].Groups[1].Value.Trim())"|Out-File $report -Append
  "PARSED_$($i+1)_EQUITY: $($matches[$i].Groups[2].Value)"|Out-File $report -Append
}
'XG_LABELS_USED_FOR_TRAINING: False'|Out-File $report -Append
'PRISTINE_BENCHMARK_USED: False'|Out-File $report -Append
Post 'xg-top5-v21/text-export' 'success' "fresh final text export has 5 explicit rollout rows"
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
if(-not$src.Contains($old)){throw 'v11 final evidence block not found'}
$patched=$src.Replace($old,$new)
$patched=$patched.Replace("Post 'xg-top5-v11/position-command'","Post 'xg-top5-v21/position-command'")
$patched=$patched.Replace("Post 'xg-top5-v11/top5-selected'","Post 'xg-top5-v21/top5-selected'")
$patched=$patched.Replace("Post 'xg-top5-v11/preset'","Post 'xg-top5-v21/preset'")
$patched=$patched.Replace("Post 'xg-top5-v11/rollout-started'","Post 'xg-top5-v21/rollout-started'")
$tmp=Join-Path $env:RUNNER_TEMP 'xg-top5-v21-generated.ps1'
Set-Content $tmp $patched -Encoding UTF8
& $tmp
if($LASTEXITCODE -ne 0){throw "Generated XG v21 runner failed with exit code $LASTEXITCODE"}
