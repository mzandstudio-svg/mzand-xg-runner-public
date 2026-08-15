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
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MZWinClose {
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string cls,string title);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@ -ErrorAction SilentlyContinue
function FindRegistrationAny(){
 $root=[System.Windows.Automation.AutomationElement]::RootElement
 $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
 foreach($w in $wins){try{if([string]$w.Current.Name -eq 'Registration'){return $w}}catch{}}
 return $null
}
function ForceCloseRegistration(){
 for($mz=0;$mz -lt 12;$mz++){
   [void](DismissRegistration 1)
   $reg=FindRegistrationAny
   $hw=[MZWinClose]::FindWindow($null,'Registration')
   if($null -eq $reg -and $hw -eq [IntPtr]::Zero){return $true}
   if($hw -ne [IntPtr]::Zero){
     [MZWinClose]::SetForegroundWindow($hw)|Out-Null
     [MZWinClose]::PostMessage($hw,0x0010,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null
     Start-Sleep -Milliseconds 700
   }
   $reg=FindRegistrationAny
   if($null -eq $reg -and [MZWinClose]::FindWindow($null,'Registration') -eq [IntPtr]::Zero){return $true}
   if($null -ne $reg){
     $close=$reg.FindFirst([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Close')))
     if($null -ne $close){try{$close.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()}catch{}}
     Start-Sleep -Milliseconds 600
   }
 }
 return ($null -eq (FindRegistrationAny) -and [MZWinClose]::FindWindow($null,'Registration') -eq [IntPtr]::Zero)
}
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
 if(-not(ForceCloseRegistration)){throw 'Registration modal still present after Win32 close attempts'}
 [void](DismissSave 1)
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
