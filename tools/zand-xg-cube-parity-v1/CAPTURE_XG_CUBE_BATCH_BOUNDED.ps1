param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$CasesPath,
  [Parameter(Mandatory=$true)][string]$OutDir
)

$ErrorActionPreference='Stop'
$srcPath=Join-Path $PSScriptRoot 'CAPTURE_XG_CUBE_BATCH.ps1'
$src=Get-Content $srcPath -Raw

# V1's Save Game probe waited up to 8 seconds every time it was called. The analysis
# loop can call it repeatedly, so a healthy 24-case batch could exceed the job timeout.
# This wrapper keeps the proven UI path but makes every polling seam bounded.
$replacements=[ordered]@{
  '$deadline=(Get-Date).AddSeconds(8)' = '$deadline=(Get-Date).AddMilliseconds(900)'
  '$deadline=(Get-Date).AddSeconds(12)' = '$deadline=(Get-Date).AddSeconds(6)'
  'for($wait=5;$wait-le40 -and -not$found;$wait+=5){' = 'for($wait=4;$wait-le24 -and -not$found -and (Get-Date)-lt$caseDeadline;$wait+=4){'
  '      Start-Sleep 5' = '      Start-Sleep 4'
  '  $caseStart=Get-Date' = "  `$caseStart=Get-Date`r`n  `$caseDeadline=`$caseStart.AddSeconds(45)`r`n  ([ordered]@{event='CASE_START';case_id=[string]`$c.case_id;utc=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress)|Out-File (Join-Path `$out 'capture-progress.jsonl') -Append -Encoding utf8"
  "    error=''" = "    error=''`r`n    timed_out=`$false"
  '    $row.cube_analysis_found=$found' = "    `$row.cube_analysis_found=`$found`r`n    if(-not`$found -and (Get-Date)-ge`$caseDeadline){`$row.timed_out=`$true;`$row.error='CASE_DEADLINE_REACHED'}"
  '  ($row|ConvertTo-Json -Compress)|Out-File $statusPath -Append -Encoding utf8' = "  (`$row|ConvertTo-Json -Compress)|Out-File `$statusPath -Append -Encoding utf8`r`n  ([ordered]@{event='CASE_END';case_id=[string]`$c.case_id;found=[bool]`$row.cube_analysis_found;timed_out=[bool]`$row.timed_out;elapsed_seconds=`$row.elapsed_seconds;utc=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress)|Out-File (Join-Path `$out 'capture-progress.jsonl') -Append -Encoding utf8"
}

foreach($kv in $replacements.GetEnumerator()){
  if(-not $src.Contains([string]$kv.Key)){throw "Bounded wrapper anchor missing: $($kv.Key)"}
  $src=$src.Replace([string]$kv.Key,[string]$kv.Value)
}

# Preserve whatever evidence exists even if a later parser/validation stage finds partial cases.
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_CUBE_BATCH_BOUNDED_GENERATED.ps1'
Set-Content $temp $src -Encoding UTF8
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
