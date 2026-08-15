param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$srcPath=Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1'
$src=Get-Content $srcPath -Raw

# Keep the proven, non-instrumented XG interaction. Inject only a read-only
# process-memory scan after XG itself has completed a verified 1-ply analysis.
$needle='$row.export_length=$text.Length;$row.analysis_found=HasAnalysis $text;$row.mentions_1ply=($text -match ''(?i)1[- ]ply'')'
if(-not $src.Contains($needle)){throw 'post-analysis injection anchor missing'}
$inject=@'
$row.export_length=$text.Length;$row.analysis_found=HasAnalysis $text;$row.mentions_1ply=($text -match '(?i)1[- ]ply')
if($row.analysis_found){
  $scanOut=Join-Path $env:MZ_MEMSCAN_OUT ([string]$c.case_id)
  New-Item -ItemType Directory -Force -Path $scanOut|Out-Null
  & python $env:MZ_MEMSCAN_SCRIPT ([string]$xg.Id) $env:MZ_MEMSCAN_REF $scanOut
  if($LASTEXITCODE -ne 0){throw "memory scanner exit $LASTEXITCODE"}
}
'@
$src=$src.Replace($needle,$inject)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_POST_ANALYSIS_MEMSCAN.ps1'
Set-Content $temp $src -Encoding utf8
$env:MZ_MEMSCAN_OUT=(Join-Path $OutDir 'memory')
$env:MZ_MEMSCAN_SCRIPT=(Join-Path $workspace 'tools\xg-nn-memory-snapshot-v1\scan_process.py')
$env:MZ_MEMSCAN_REF=(Join-Path $workspace 'tools\xg-nn-memory-snapshot-v1\start_reference.json')
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
