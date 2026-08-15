param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$srcPath=Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1'
$src=Get-Content $srcPath -Raw
$needle='InvokeOnePly;$row.one_ply_command_sent=$true'
if(-not $src.Contains($needle)){throw 'one-ply anchor missing'}
$inject=@'
$watchOut=Join-Path $env:MZ_WATCH_OUT ([string]$c.case_id)
New-Item -ItemType Directory -Force -Path $watchOut|Out-Null
$watchStd=Join-Path $watchOut 'watch-stdout.txt'; $watchErr=Join-Path $watchOut 'watch-stderr.txt'
$watch=Start-Process python -ArgumentList @($env:MZ_WATCH_SCRIPT,[string]$xg.Id,$watchOut) -PassThru -RedirectStandardOutput $watchStd -RedirectStandardError $watchErr
Start-Sleep -Milliseconds 800
InvokeOnePly;$row.one_ply_command_sent=$true
'@
$src=$src.Replace($needle,$inject)
$needle2='$row.elapsed_seconds=[math]::Round(((Get-Date)-$s).TotalSeconds,3);($row|ConvertTo-Json -Compress)|Out-File $status -Append -Encoding utf8'
if(-not $src.Contains($needle2)){throw 'row completion anchor missing'}
$inject2=@'
if($null -ne $watch){
  try{Wait-Process -Id $watch.Id -Timeout 45 -ErrorAction SilentlyContinue}catch{}
  if(-not $watch.HasExited){Stop-Process -Id $watch.Id -Force -ErrorAction SilentlyContinue}
}
$row.elapsed_seconds=[math]::Round(((Get-Date)-$s).TotalSeconds,3);($row|ConvertTo-Json -Compress)|Out-File $status -Append -Encoding utf8
'@
$src=$src.Replace($needle2,$inject2)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_TRANSIENT_NN.ps1';Set-Content $temp $src -Encoding utf8
$env:MZ_WATCH_OUT=(Join-Path $OutDir 'watch')
$env:MZ_WATCH_SCRIPT=(Join-Path $workspace 'tools\xg-nn-transient-watch-v1\watch_transient.py')
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
