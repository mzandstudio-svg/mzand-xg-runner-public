$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-top5-rollout-run.ps1'
$src=Get-Content $srcPath -Raw
$old=@'
'FINAL_ROLLOUT_EVIDENCE_CAPTURED: True'|Out-File $report -Append
Post 'xg-top5-v11/final-evidence' 'success' "Final rollout evidence captured at elapsed=$elapsed idleStreak=$idleStreak"
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$new=@'
'FINAL_ROLLOUT_EVIDENCE_CAPTURED: True'|Out-File $report -Append
Post 'xg-top5-v19/final-evidence' 'success' "Final rollout evidence captured at elapsed=$elapsed idleStreak=$idleStreak"

# Export the final analysis text so the runner is useful headlessly, not just visually.
$script:xg.Refresh()
[R11N]::SetForegroundWindow([IntPtr]$script:xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 350
[System.Windows.Forms.SendKeys]::SendWait('^c')
Start-Sleep 1
try{$text=[string](Get-Clipboard -Raw -TextFormatType Text)}catch{$text=[string](Get-Clipboard -Raw)}
$export="$env:GITHUB_WORKSPACE\xg-top5-v19-export.txt"
Set-Content $export $text -Encoding UTF8
"FINAL_EXPORT_LENGTH: $($text.Length)"|Out-File $report -Append
if($text.Length-lt100){throw "Final XG rollout export too short: $($text.Length)"}
$matches=[regex]::Matches($text,'(?m)^\s*\d+\.\s+(.+?)\s+eq:([+-]\d+\.\d+)')
"FINAL_EXPORT_CANDIDATE_ROWS: $($matches.Count)"|Out-File $report -Append
if($matches.Count-lt1){throw 'No candidate equity rows parsed from final XG rollout export'}
$rolloutMention=[regex]::IsMatch($text,'(?i)rollout|XG Roller')
"FINAL_EXPORT_ROLLOUT_MENTION: $rolloutMention"|Out-File $report -Append
for($i=0;$i-lt[math]::Min(5,$matches.Count);$i++){
  "PARSED_$($i+1)_MOVE: $($matches[$i].Groups[1].Value.Trim())"|Out-File $report -Append
  "PARSED_$($i+1)_EQUITY: $($matches[$i].Groups[2].Value)"|Out-File $report -Append
}
'XG_LABELS_USED_FOR_TRAINING: False'|Out-File $report -Append
'PRISTINE_BENCHMARK_USED: False'|Out-File $report -Append
Post 'xg-top5-v19/text-export' 'success' "final text export candidates=$($matches.Count) rolloutMention=$rolloutMention"
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
if(-not$src.Contains($old)){throw 'v11 final evidence block not found'}
$patched=$src.Replace($old,$new)
$patched=$patched.Replace("Post 'xg-top5-v11/position-command'","Post 'xg-top5-v19/position-command'")
$patched=$patched.Replace("Post 'xg-top5-v11/top5-selected'","Post 'xg-top5-v19/top5-selected'")
$patched=$patched.Replace("Post 'xg-top5-v11/preset'","Post 'xg-top5-v19/preset'")
$patched=$patched.Replace("Post 'xg-top5-v11/rollout-started'","Post 'xg-top5-v19/rollout-started'")
$tmp=Join-Path $env:RUNNER_TEMP 'xg-top5-v19-generated.ps1'
Set-Content $tmp $patched -Encoding UTF8
& $tmp
