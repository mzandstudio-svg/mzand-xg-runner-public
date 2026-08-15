param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$src=Get-Content (Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1') -Raw
$needle='$row.export_length=$text.Length;$row.analysis_found=HasAnalysis $text;$row.mentions_1ply=($text -match ''(?i)1[- ]ply'')'
if(-not $src.Contains($needle)){throw 'post-analysis anchor missing'}
$inject=@'
$row.export_length=$text.Length;$row.analysis_found=HasAnalysis $text;$row.mentions_1ply=($text -match '(?i)1[- ]ply')
if($row.analysis_found -and $row.mentions_1ply){
  $scanOut=Join-Path $env:MZ_OUTPUTSCAN_OUT ([string]$c.case_id)
  New-Item -ItemType Directory -Force -Path $scanOut|Out-Null
  & python $env:MZ_OUTPUTSCAN_SCRIPT ([string]$xg.Id) $scanOut
  if($LASTEXITCODE -ne 0){throw "output memory scanner exit $LASTEXITCODE"}
}
'@
$src=$src.Replace($needle,$inject)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_OUTPUT_MEMSCAN.ps1';Set-Content $temp $src -Encoding utf8
$env:MZ_OUTPUTSCAN_OUT=(Join-Path $OutDir 'memory')
$env:MZ_OUTPUTSCAN_SCRIPT=(Join-Path $workspace 'tools\xg-nn-output-memory-v1\scan_output.py')
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
