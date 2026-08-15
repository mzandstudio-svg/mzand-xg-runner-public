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
 # This is only a UI diagnostic. Close the normal trial Registration dialog,
 # then enumerate the Analyze menu. No activation/licensing state is modified.
 [void](DismissRegistration 15)
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('%a')
 Start-Sleep 2
 $root=[System.Windows.Automation.AutomationElement]::RootElement
 $lines=New-Object 'System.Collections.Generic.List[string]'
 $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
 foreach($el in $all){
   try{
     $name=[string]$el.Current.Name
     $pid=$el.Current.ProcessId
     $ct=[string]$el.Current.ControlType.ProgrammaticName
     $cls=[string]$el.Current.ClassName
     if($pid -eq $xg.Id -or $ct -match 'Menu|MenuItem'){
       $r=$el.Current.BoundingRectangle
       $lines.Add("PID=[$pid] Name=[$name] Type=[$ct] Class=[$cls] Id=[$($el.Current.AutomationId)] Enabled=[$($el.Current.IsEnabled)] Offscreen=[$($el.Current.IsOffscreen)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
     }
   }catch{}
 }
 $lines|Out-File (Join-Path $env:MZ_MENU_OUT 'analyze-menu-ui.txt') -Encoding utf8
 Shot (Join-Path $env:MZ_MENU_OUT 'analyze-menu.png')
 [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
}
'@
if(-not $src.Contains($old)){throw 'InvokeOnePly anchor missing'}
$src=$src.Replace($old,$new)
# Avoid waiting for analysis: this run only needs the menu dump above.
$src=$src.Replace("function HasAnalysis([string]$t){return ($t -match '(?i)1[- ]ply|Player\\s*Winning Chances:|Cubeful Equities|Best Cube action:|(?m)^\\s*1\\.\\s+')}","function HasAnalysis([string]`$t){return `$true}")
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_ANALYZE_MENU_V2.ps1'
Set-Content $temp $src -Encoding utf8
$env:MZ_MENU_OUT=$OutDir
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
