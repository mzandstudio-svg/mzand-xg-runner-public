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
 [void](DismissRegistration 2)
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('%a')
 Start-Sleep 1
 $root=[System.Windows.Automation.AutomationElement]::RootElement
 $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
 $target=$null
 foreach($el in $all){
   try{if([string]$el.Current.Name -eq 'Set Analyze Level'){$target=$el;break}}catch{}
 }
 if($null -eq $target){throw 'Set Analyze Level menu item not found'}
 try{$target.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()}catch{
   $r=$target.Current.BoundingRectangle
   [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point([int]($r.X+$r.Width/2),[int]($r.Y+$r.Height/2))
   [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
 }
 Start-Sleep 2
 $lines=New-Object 'System.Collections.Generic.List[string]'
 $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
 foreach($w in $wins){
   try{
     if($w.Current.ProcessId -ne $xg.Id){continue}
     $lines.Add("WINDOW Name=[$($w.Current.Name)] Class=[$($w.Current.ClassName)] Id=[$($w.Current.AutomationId)] Handle=[$($w.Current.NativeWindowHandle)]")
     $nodes=$w.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
     foreach($n in $nodes){
       try{
         $r=$n.Current.BoundingRectangle
         $lines.Add("  Name=[$($n.Current.Name)] Type=[$($n.Current.ControlType.ProgrammaticName)] Class=[$($n.Current.ClassName)] Id=[$($n.Current.AutomationId)] Enabled=[$($n.Current.IsEnabled)] Offscreen=[$($n.Current.IsOffscreen)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
       }catch{}
     }
   }catch{}
 }
 $lines|Out-File (Join-Path $env:MZ_LEVEL_OUT 'analyze-level-ui.txt') -Encoding utf8
 Shot (Join-Path $env:MZ_LEVEL_OUT 'analyze-level.png')
 [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
}
'@
if(-not $src.Contains($old)){throw 'InvokeOnePly anchor missing'}
$src=$src.Replace($old,$new)
$temp=Join-Path $env:RUNNER_TEMP 'CAPTURE_XG_ANALYZE_LEVEL_DUMP.ps1';Set-Content $temp $src -Encoding utf8
$env:MZ_LEVEL_OUT=$OutDir
& $temp -ExePath $ExePath -CasesPath $CasesPath -OutDir $OutDir
