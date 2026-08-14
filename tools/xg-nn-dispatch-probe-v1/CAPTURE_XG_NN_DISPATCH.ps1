param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$CasesPath,
  [Parameter(Mandatory=$true)][string]$OutDir
)

$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$base=Join-Path $workspace 'tools\zand-xg-cube-parity-v1\CAPTURE_XG_CUBE_BATCH.ps1'
$src=Get-Content $base -Raw

$repl=[ordered]@{
  'if($cases.Count -ne 24){throw "Expected 24 parity cases, got $($cases.Count)"}' = 'if($cases.Count -ne 5){throw "Expected 5 NN dispatch cases, got $($cases.Count)"}'
  '$deadline=(Get-Date).AddSeconds(8)' = '$deadline=(Get-Date).AddMilliseconds(900)'
  '$deadline=(Get-Date).AddSeconds(12)' = '$deadline=(Get-Date).AddSeconds(6)'
  'for($wait=5;$wait-le40 -and -not$found;$wait+=5){' = 'for($wait=2;$wait-le16 -and -not$found -and (Get-Date)-lt$caseDeadline;$wait+=2){'
  '      Start-Sleep 5' = '      Start-Sleep 2'
  '  $caseStart=Get-Date' = "  `$caseStart=Get-Date`r`n  `$caseDeadline=`$caseStart.AddSeconds(30)"
  "    error=''" = "    error=''`r`n    timed_out=`$false"
  '    $row.cube_analysis_found=$found' = "    `$row.cube_analysis_found=`$found`r`n    if(-not`$found -and (Get-Date)-ge`$caseDeadline){`$row.timed_out=`$true;`$row.error='CASE_DEADLINE_REACHED'}"
  "  return ((`$text-match'Best Cube action:') -or ((`$text-match'Cubeful Equities') -and (`$text-match'No double:')))" = "  return ((`$text-match'Player\\s+Winning Chances:') -or (`$text-match'Best Cube action:') -or ((`$text-match'Cubeful Equities') -and (`$text-match'No double:')))"
}
foreach($kv in $repl.GetEnumerator()){
  if(-not $src.Contains([string]$kv.Key)){throw "NN probe anchor missing: $($kv.Key)"}
  $src=$src.Replace([string]$kv.Key,[string]$kv.Value)
}

# The first-run wizard in the proven prefix creates the Settings registry key.
# Inject the requested direct-NN level only after that prefix is complete, immediately
# before the case loop. XG's own language/config assets label level 0 as 1-ply.
$anchor='$successCount=0'
$inject=@'
$successCount=0
$settings='HKCU:\Software\GameSite 2000\eXtreme Gammon 2\Settings'
New-Item -Path $settings -Force | Out-Null
New-ItemProperty -Path $settings -Name BotAnalyzeLevel -PropertyType DWord -Value 0 -Force | Out-Null
New-ItemProperty -Path $settings -Name TopAnalyzeLevel -PropertyType DWord -Value 0 -Force | Out-Null
$regReport=Join-Path $out 'analyze-level-registry.txt'
@(
  'REQUESTED_LEVEL=0',
  ('BotAnalyzeLevel=' + (Get-ItemPropertyValue -Path $settings -Name BotAnalyzeLevel)),
  ('TopAnalyzeLevel=' + (Get-ItemPropertyValue -Path $settings -Name TopAnalyzeLevel))
) | Out-File $regReport -Encoding utf8
'@
if(-not $src.Contains($anchor)){throw 'successCount anchor missing'}
$src=$src.Replace($anchor,$inject)

$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_NN_DISPATCH_GENERATED.ps1'
Set-Content $temp $src -Encoding UTF8
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
