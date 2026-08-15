param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$srcPath=Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1'
$src=Get-Content $srcPath -Raw
$old="[System.Windows.Forms.SendKeys]::SendWait('^1')"
if(-not $src.Contains($old)){throw 'Ctrl+1 anchor missing'}
$src=$src.Replace($old,"[System.Windows.Forms.SendKeys]::SendWait('^0')")
$src=$src.Replace("'DIRECT_NN_COMMAND=Ctrl+1'","'DIRECT_NN_COMMAND=Ctrl+0'")
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_ZERO_PLY_GENERATED.ps1'
Set-Content $temp $src -Encoding utf8
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
