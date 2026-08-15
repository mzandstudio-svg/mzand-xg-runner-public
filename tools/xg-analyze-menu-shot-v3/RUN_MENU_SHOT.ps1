param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$src=Get-Content (Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1') -Raw
$old=@'
function InvokeOnePly(){
 [void](DismissRegistration 2)
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('^1')
}
'@
$new=@'
function InvokeOnePly(){
 [void](DismissRegistration 15)
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('%a')
 Start-Sleep 2
 Shot (Join-Path $env:MZ_MENU_OUT 'analyze-menu-open.png')
 [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
}
'@
if(-not $src.Contains($old)){throw 'InvokeOnePly anchor missing'}
$src=$src.Replace($old,$new)
# Short-circuit the analysis polling loop: screenshot is the only target.
$src=[regex]::Replace($src,'function HasAnalysis\(\[string\]\$t\)\{return \(\$t -match .*?\)\}','function HasAnalysis([string]$t){return $true}')
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_ANALYZE_MENU_SHOT_V3.ps1'
Set-Content $temp $src -Encoding utf8
$env:MZ_MENU_OUT=$OutDir
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
