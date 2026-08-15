param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$ModelPath,
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
  $scanOut=Join-Path $env:MZ_OBJ_OUT ([string]$c.case_id)
  New-Item -ItemType Directory -Force -Path $scanOut|Out-Null
  & python $env:MZ_OBJ_SCRIPT ([string]$xg.Id) $env:MZ_OBJ_MODEL $scanOut
  if($LASTEXITCODE -ne 0){throw "NN object decoder exit $LASTEXITCODE"}
}
'@
$src=$src.Replace($needle,$inject)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_NN_OBJECT_DECODE.ps1';Set-Content $temp $src -Encoding utf8
$env:MZ_OBJ_OUT=(Join-Path $OutDir 'memory')
$env:MZ_OBJ_SCRIPT=(Join-Path $workspace 'tools\xg-nn-object-decode-v1\decode_object.py')
$env:MZ_OBJ_MODEL=$ModelPath
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
