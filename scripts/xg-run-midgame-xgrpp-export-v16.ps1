$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-run-midgame-xgrpp-export-v15.ps1'
$src=Get-Content $srcPath -Raw

$oldExport=@'
function ExportText(){
  $xg.Refresh(); [V15N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null; Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^c'); Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
'@
$newExport=@'
function ExportText(){
  $xg.Refresh(); [V15N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null; Start-Sleep -Milliseconds 250
  # XG copies only the bare XGID while the board/editor owns focus. Select the
  # first analyzed move row before Ctrl+C so the clipboard contains the full
  # structured Top-N analysis. Coordinates are main-window relative and match
  # the same first-row anchor already used by the historical XGR++ runner.
  $focusRect=New-Object V15N+RECT
  if([V15N]::GetWindowRect([IntPtr]$xg.MainWindowHandle,[ref]$focusRect)){
    LeftClick ($focusRect.Left+130) ($focusRect.Top+364)
    Start-Sleep -Milliseconds 300
  }
  [System.Windows.Forms.SendKeys]::SendWait('^c'); Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
'@
if(-not$src.Contains($oldExport)){throw 'v15 ExportText block not found'}
$src=$src.Replace($oldExport,$newExport)

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
for($baselineAttempt=1;$baselineAttempt-le3;$baselineAttempt++){
  $baseline=ExportText
  $beforeSource=TopSource $baseline
  $looksLikeXgid=$baseline.Trim().StartsWith('XGID=')
  $structuredEnough=($baseline.Length-gt100 -and -not$looksLikeXgid)
  "BASELINE_ATTEMPT_${baselineAttempt}_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_SOURCE: $beforeSource"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_XGID_ONLY: $looksLikeXgid"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_STRUCTURED_ENOUGH: $structuredEnough"|Out-File $report15 -Append
  if($beforeSource -or ($env:MZAND_XG_BASELINE_ONLY-eq'1' -and $structuredEnough)){break}
  $retryDismissed=DismissDelayedSaveGame
  "BASELINE_ATTEMPT_${baselineAttempt}_SAVE_DISMISSED: $retryDismissed"|Out-File $report15 -Append
  InvokeAnalyzePosition
  Post 'xg-public-v16/midgame-analyze-retry' 'success' "baseline attempt $baselineAttempt reissued Analyze Position"
  Start-Sleep 20
  Shot "$env:GITHUB_WORKSPACE\xg-v16-baseline-retry-${baselineAttempt}.png"
}
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if($env:MZAND_XG_BASELINE_ONLY-eq'1'){
  if($baseline.Length-le100 -or $baseline.Trim().StartsWith('XGID=')){throw 'No structured baseline export after bounded retries'}
}else{
  if(-not$beforeSource){throw 'Could not parse baseline top candidate source after 3 bounded analysis retries'}
}
'@

if(-not$src.Contains($old)){throw 'v15 baseline block not found'}
$patched=$src.Replace($old,$new)
$tmp=Join-Path $env:RUNNER_TEMP 'xg-v16-patched.ps1'
Set-Content $tmp $patched -Encoding UTF8
& $tmp
