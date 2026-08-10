$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-run-midgame-xgrpp-export-v15.ps1'
$src=Get-Content $srcPath -Raw

$old=@'
$baseline=ExportText
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
$beforeSource=TopSource $baseline
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source'}
'@

$new=@'
$baseline=''
$beforeSource=''
for($baselineAttempt=1;$baselineAttempt-le3 -and -not$beforeSource;$baselineAttempt++){
  $baseline=ExportText
  $beforeSource=TopSource $baseline
  $looksLikeXgid=$baseline.Trim().StartsWith('XGID=')
  "BASELINE_ATTEMPT_${baselineAttempt}_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_SOURCE: $beforeSource"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_XGID_ONLY: $looksLikeXgid"|Out-File $report15 -Append
  if($beforeSource){break}
  if($looksLikeXgid -or $baseline.Length-lt100){
    $retryDismissed=DismissDelayedSaveGame
    "BASELINE_ATTEMPT_${baselineAttempt}_SAVE_DISMISSED: $retryDismissed"|Out-File $report15 -Append
    InvokeAnalyzePosition
    Post 'xg-public-v16/midgame-analyze-retry' 'success' "baseline attempt $baselineAttempt reissued Analyze Position"
    Start-Sleep 20
    Shot "$env:GITHUB_WORKSPACE\xg-v16-baseline-retry-${baselineAttempt}.png"
  }
}
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source after 3 bounded analysis retries'}
'@

if(-not$src.Contains($old)){throw 'v15 baseline block not found'}
$patched=$src.Replace($old,$new)
$tmp=Join-Path $env:RUNNER_TEMP 'xg-v16-patched.ps1'
Set-Content $tmp $patched -Encoding UTF8
& $tmp
