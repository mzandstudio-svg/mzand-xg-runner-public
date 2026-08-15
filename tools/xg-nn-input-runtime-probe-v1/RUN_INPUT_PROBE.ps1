param(
 [Parameter(Mandatory=$true)][string]$ExePath,
 [Parameter(Mandatory=$true)][string]$ModelPath,
 [Parameter(Mandatory=$true)][string]$CasesPath,
 [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
$hookOut=Join-Path $OutDir 'hook'; New-Item -ItemType Directory -Force -Path $hookOut|Out-Null
$srcPath=Join-Path $workspace 'tools\xg-nn-dispatch-probe-v2\CAPTURE_XG_NN_DISPATCH_V2.ps1'
$src=Get-Content $srcPath -Raw
$needle="if(`$xg.HasExited){throw 'XG exited after restart'}"
if(-not $src.Contains($needle)){throw 'capture injection anchor missing'}
$inject=@'

# NN input probe injection: attach Frida before any 1-ply command.
$hookLog=Join-Path $env:NIP_HOOK_OUT 'hook-stdout.txt'
$hookErr=Join-Path $env:NIP_HOOK_OUT 'hook-stderr.txt'
$hp=Start-Process python -ArgumentList @($env:NIP_HOOK,[string]$xg.Id) -PassThru -RedirectStandardOutput $hookLog -RedirectStandardError $hookErr
$ready=Join-Path $env:NIP_HOOK_OUT 'READY';$fatal=Join-Path $env:NIP_HOOK_OUT 'FATAL'
$deadline=(Get-Date).AddSeconds(35)
while((Get-Date) -lt $deadline -and -not(Test-Path $ready) -and -not(Test-Path $fatal)){Start-Sleep -Milliseconds 250}
if(Test-Path $fatal){throw ('Frida fatal before ready: '+(Get-Content $fatal -Raw))}
if(-not(Test-Path $ready)){throw 'Frida hook did not become ready'}
'@
$src=$src.Replace($needle,$needle+$inject)
# Give the hook a few seconds after both duplicated START analyses before XG is killed.
$killNeedle="Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue"
$killInject=@'
$done=Join-Path $env:NIP_HOOK_OUT 'DONE';$deadline=(Get-Date).AddSeconds(12)
while((Get-Date) -lt $deadline -and -not(Test-Path $done)){Start-Sleep -Milliseconds 250}
'@
if(-not $src.Contains($killNeedle)){throw 'capture kill anchor missing'}
$src=$src.Replace($killNeedle,$killInject+"`n"+$killNeedle)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_NN_INPUT_INSTRUMENTED.ps1';Set-Content $temp $src -Encoding utf8
$env:NIP_MODEL=$ModelPath;$env:NIP_HOOK=(Join-Path $workspace 'tools\xg-nn-input-runtime-probe-v1\hook_nn.py');$env:NIP_HOOK_OUT=$hookOut
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
