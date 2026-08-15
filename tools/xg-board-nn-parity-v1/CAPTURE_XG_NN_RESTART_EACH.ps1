param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$CasesPath,
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$srcPath=Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1'
$src=Get-Content $srcPath -Raw
$anchor='foreach($c in $cases){'
if(-not $src.Contains($anchor)){throw 'foreach anchor missing'}
$insert=@'
foreach($c in $cases){
 # Scientific isolation: every oracle case starts from a fresh XG process.
 Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
 Start-Sleep -Milliseconds 900
 $xg=Start-Process $env:xgexe -WorkingDirectory (Split-Path -Parent $env:xgexe) -PassThru
 Start-Sleep 5
 $xg.Refresh(); if($xg.HasExited){throw 'XG exited during per-case restart'}
 [void](DismissRegistration 10)
'@
$src=$src.Replace($anchor,$insert)
$temp=Join-Path $env:RUNNER_TEMP 'xg-nn-restart-each-generated.ps1'
Set-Content $temp $src -Encoding UTF8
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
