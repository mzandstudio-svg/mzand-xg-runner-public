$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V14N {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function Post([string]$context,[string]$state,[string]$description){
  try{
    $payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress
    $headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'}
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null
  }catch{}
}
function Shot([string]$name){
  $b=[System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height
  $g=[System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size)
  $bmp.Save("$env:GITHUB_WORKSPACE\$name.png",[System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose();$bmp.Dispose()
}
function DumpUI([string]$name,[int]$processId){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $lines=New-Object 'System.Collections.Generic.List[string]'
  foreach($e in $all){
    try{
      $r=$e.Current.BoundingRectangle
      if($e.Current.ProcessId-eq$processId -or $e.Current.ClassName-eq'#32768' -or $e.Current.ClassName-eq'#32770'){
        $lines.Add("PID=[$($e.Current.ProcessId)] Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
      }
    }catch{}
  }
  $lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8
}
function LeftClick([int]$x,[int]$y){
  [V14N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V14N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V14N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function RightClick([int]$x,[int]$y){
  [V14N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V14N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V14N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
}
function LargeRolloutSubmenu($root,[int]$processId){
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $subs=@()
  foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$processId -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$subs+=,$e}}catch{}}
  return @($subs)
}

function Stop-Process {
  [CmdletBinding()]
  param([Parameter(ValueFromPipeline=$true)]$InputObject,[string[]]$Name,[int[]]$Id,[switch]$Force)
  process { }
}
. ./scripts/xg-top5-rollout-submenu-probe.ps1
Remove-Item Function:\Stop-Process -Force

$report="$env:GITHUB_WORKSPACE\xg-top5-v14-report.txt"
'XG Top5 Rollout v14 Explicit 3-ply XG Roller Preset'|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh();if($xg.HasExited){throw 'XG exited'}
$root=[System.Windows.Automation.AutomationElement]::RootElement

# Save stable main-window geometry from UI Automation before closing the popup.
$tops=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$mainWins=@()
foreach($e in $tops){try{if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'TMainX'){$mainWins+=,$e}}catch{}}
if($mainWins.Count-ne1){throw "Expected one XG TMainX window, got $($mainWins.Count)"}
$mr=$mainWins[0].Current.BoundingRectangle
$rowX=[int]($mr.X+130);$row5Y=[int]($mr.Y+542)
"MAIN_RECT: $($mr.X),$($mr.Y),$($mr.Width),$($mr.Height)"|Out-File $report -Append

$subs=LargeRolloutSubmenu $root $xg.Id
if($subs.Count-ne1){Shot 'xg-top5-v14-initial-submenu-mismatch';DumpUI 'xg-top5-v14-initial-submenu-mismatch' $xg.Id;throw "Expected initial Rollout submenu, got $($subs.Count)"}
$sub=$subs[0];$sr=$sub.Current.BoundingRectangle
$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$preset=@()
foreach($e in $desc){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 18'){$preset+=,$e}}catch{}}
if($preset.Count-ne1){throw "Expected preset Item 18 once, got $($preset.Count)"}
$pr=$preset[0].Current.BoundingRectangle;$pdelta=[int]($pr.Y-$sr.Y)
"PRESET_ITEM_ID: $($preset[0].Current.AutomationId)"|Out-File $report -Append
"PRESET_ITEM_RECT: $($pr.X),$($pr.Y),$($pr.Width),$($pr.Height)"|Out-File $report -Append
"PRESET_Y_DELTA: $pdelta"|Out-File $report -Append
if($pdelta-lt55 -or $pdelta-gt70){throw "Unexpected 3-ply XG Roller preset geometry delta=$pdelta"}
LeftClick ([int]($pr.X+$pr.Width/2)) ([int]($pr.Y+$pr.Height/2))
Post 'xg-top5-v14/preset-selected' 'success' 'Explicit Rollout preset Item 18 selected'
Start-Sleep -Milliseconds 700

# Re-open context menu using the saved XG UI geometry.
RightClick $rowX $row5Y
Start-Sleep -Milliseconds 700
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$contexts=@()
foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt200 -and $r.Width-lt260 -and $r.Height-gt400){$contexts+=,$e}}catch{}}
if($contexts.Count-ne1){Shot 'xg-top5-v14-context-mismatch';DumpUI 'xg-top5-v14-context-mismatch' $xg.Id;throw "Expected context popup once, got $($contexts.Count)"}
$cr=$contexts[0].Current.BoundingRectangle
[V14N]::SetCursorPos([int]($cr.X+$cr.Width/2),[int]($cr.Y+221))|Out-Null
Start-Sleep 1

$subs=LargeRolloutSubmenu $root $xg.Id
if($subs.Count-ne1){Shot 'xg-top5-v14-second-submenu-mismatch';DumpUI 'xg-top5-v14-second-submenu-mismatch' $xg.Id;throw "Expected reopened Rollout submenu, got $($subs.Count)"}
$sub=$subs[0];$sr=$sub.Current.BoundingRectangle
$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$start=@()
foreach($e in $desc){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 27'){$start+=,$e}}catch{}}
if($start.Count-ne1){throw "Expected Start Item 27 once, got $($start.Count)"}
$rr=$start[0].Current.BoundingRectangle;$sdelta=[int]($rr.Y-$sr.Y)
"START_ITEM_ID: $($start[0].Current.AutomationId)"|Out-File $report -Append
"START_Y_DELTA: $sdelta"|Out-File $report -Append
if($sdelta-lt225 -or $sdelta-gt240){throw "Unexpected Start geometry delta=$sdelta"}
LeftClick ([int]($rr.X+$rr.Width/2)) ([int]($rr.Y+$rr.Height/2))
Post 'xg-top5-v14/start-clicked' 'success' 'Start clicked after explicit preset selection'
Start-Sleep 1
Shot 'xg-top5-v14-prompt-1s';DumpUI 'xg-top5-v14-prompt-1s' $xg.Id
Start-Sleep 3
Shot 'xg-top5-v14-prompt-4s';DumpUI 'xg-top5-v14-prompt-4s' $xg.Id
Post 'xg-top5-v14/prompt-captured' 'success' 'Prompt captured after explicit 3-ply XG Roller preset selection'
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
