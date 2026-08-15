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

# Attach only after ImportVerified() has succeeded. Attaching during XG startup
# changes modal timing and can interfere with clipboard-based position import.
$old=@'
function InvokeOnePly(){
 [void](DismissRegistration 2)
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('^1')
}
'@
$new=@'
function InvokeOnePly(){
 [void](DismissSave 1)
 [void](DismissRegistration 2)
 FocusXg
 $ready=Join-Path $env:NIP_HOOK_OUT 'READY';$fatal=Join-Path $env:NIP_HOOK_OUT 'FATAL'
 if(-not(Test-Path $ready)){
   $hookLog=Join-Path $env:NIP_HOOK_OUT 'hook-stdout.txt'
   $hookErr=Join-Path $env:NIP_HOOK_OUT 'hook-stderr.txt'
   $script:NIP_HOOK_PROCESS=Start-Process python -ArgumentList @($env:NIP_HOOK,[string]$xg.Id) -PassThru -RedirectStandardOutput $hookLog -RedirectStandardError $hookErr
   $deadline=(Get-Date).AddSeconds(150)
   while((Get-Date) -lt $deadline -and -not(Test-Path $ready) -and -not(Test-Path $fatal)){Start-Sleep -Milliseconds 250}
   if(Test-Path $fatal){throw ('Frida fatal before ready: '+(Get-Content $fatal -Raw))}
   if(-not(Test-Path $ready)){throw 'Frida hook did not become ready within 150s'}
 }
 # Frida attach can cause the Trial Registration window to reappear after the
 # position was already verified. Clear any post-attach modal before Ctrl+1.
 for($mz=0;$mz -lt 8;$mz++){
   [void](DismissSave 1)
   [void](DismissRegistration 1)
   Start-Sleep -Milliseconds 150
 }
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('^1')
}
'@
if(-not $src.Contains($old)){throw 'InvokeOnePly anchor missing'}
$src=$src.Replace($old,$new)

# Give the hook time to capture the first real evaluator access before XG exits.
$killNeedle="Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue"
$killInject=@'
$ready=Join-Path $env:NIP_HOOK_OUT 'READY'
if(Test-Path $ready){
  $done=Join-Path $env:NIP_HOOK_OUT 'DONE';$deadline=(Get-Date).AddSeconds(30)
  while((Get-Date) -lt $deadline -and -not(Test-Path $done)){Start-Sleep -Milliseconds 250}
}
'@
if(-not $src.Contains($killNeedle)){throw 'capture kill anchor missing'}
$src=$src.Replace($killNeedle,$killInject+"`n"+$killNeedle)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_NN_INPUT_INSTRUMENTED.ps1';Set-Content $temp $src -Encoding utf8
$env:NIP_MODEL=$ModelPath;$env:NIP_HOOK=(Join-Path $workspace 'tools\xg-nn-input-runtime-probe-v1\hook_nn.py');$env:NIP_HOOK_OUT=$hookOut
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
