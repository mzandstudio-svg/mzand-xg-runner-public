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

# Start a legitimate long XG analysis BEFORE attaching instrumentation.  Frida
# attachment can surface the normal trial-registration dialog; starting first
# avoids making that dialog the cause of a missing evaluator call.
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
 # Ctrl+Shift+R = XG Roller++ in XG's analysis UI. This is used only to keep
 # the evaluator busy long enough to observe its already-running NN accesses.
 [System.Windows.Forms.SendKeys]::SendWait('^+r')
 Start-Sleep -Milliseconds 350

 $ready=Join-Path $env:AA_HOOK_OUT 'READY';$fatal=Join-Path $env:AA_HOOK_OUT 'FATAL';$done=Join-Path $env:AA_HOOK_OUT 'DONE'
 $hookLog=Join-Path $env:AA_HOOK_OUT 'hook-stdout.txt';$hookErr=Join-Path $env:AA_HOOK_OUT 'hook-stderr.txt'
 $script:AA_HOOK_PROCESS=Start-Process python -ArgumentList @($env:AA_HOOK,[string]$xg.Id) -PassThru -RedirectStandardOutput $hookLog -RedirectStandardError $hookErr
 $deadline=(Get-Date).AddSeconds(18)
 while((Get-Date)-lt$deadline -and -not(Test-Path $ready) -and -not(Test-Path $fatal) -and -not(Test-Path $done)){Start-Sleep -Milliseconds 100}
 if(Test-Path $fatal){throw ('Frida active-access fatal: '+(Get-Content $fatal -Raw))}

 # Close only the ordinary trial dialog if attach caused it to surface. This
 # does not activate/bypass licensing; it is the same Close action used in the
 # normal trial UI. Do not restart the analysis command here.
 for($q=0;$q-lt4;$q++){
   if($null-eq(FindDialog 'Registration')){break}
   [void](DismissRegistration 2)
   Start-Sleep -Milliseconds 250
 }

 $wait=(Get-Date).AddSeconds(35)
 while((Get-Date)-lt$wait -and -not(Test-Path $done) -and -not(Test-Path $fatal)){Start-Sleep -Milliseconds 100}
 if(Test-Path $fatal){throw ('Frida active-access fatal after ready: '+(Get-Content $fatal -Raw))}
}
'@
if(-not $src.Contains($old)){throw 'InvokeOnePly anchor missing'}
$src=$src.Replace($old,$new)

# Do not wait for a clipboard analysis export as the scientific endpoint. The
# hook evidence is primary. Give XG a bounded interval, then preserve normal
# capture status/screenshots as secondary evidence.
$src=$src.Replace("Start-Sleep 2`n   if(DismissSave 2){InvokeOnePly}","Start-Sleep 1")
$src=$src.Replace("$deadline=(Get-Date).AddSeconds(24)","$deadline=(Get-Date).AddSeconds(8)")

$killNeedle="Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue"
$killInject=@'
if($null-ne$script:AA_HOOK_PROCESS){
 try{Wait-Process -Id $script:AA_HOOK_PROCESS.Id -Timeout 3 -ErrorAction SilentlyContinue}catch{}
 if(-not$script:AA_HOOK_PROCESS.HasExited){Stop-Process -Id $script:AA_HOOK_PROCESS.Id -Force -ErrorAction SilentlyContinue}
}
'@
if(-not $src.Contains($killNeedle)){throw 'kill anchor missing'}
$src=$src.Replace($killNeedle,$killInject+"`n"+$killNeedle)

$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_NN_ACTIVE_ACCESS.ps1'; Set-Content $temp $src -Encoding utf8
$env:NIP_MODEL=$ModelPath
$env:NIP_HOOK_OUT=$hookOut
$env:AA_HOOK_OUT=$hookOut
$env:AA_HOOK=(Join-Path $workspace 'tools\xg-nn-input-runtime-probe-v1\hook_nn.py')
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
