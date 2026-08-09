$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V17N {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function Post([string]$context,[string]$state,[string]$description){try{$payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress;$headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'};Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null}catch{}}
function Shot([string]$name){$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save("$env:GITHUB_WORKSPACE\$name.png",[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}
function DumpUI([string]$name,[int]$processId){$root=[System.Windows.Automation.AutomationElement]::RootElement;$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition);$lines=New-Object 'System.Collections.Generic.List[string]';foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$processId -or $e.Current.ClassName-eq'#32768' -or $e.Current.ClassName-eq'#32770'){$lines.Add("PID=[$($e.Current.ProcessId)] Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")}}catch{}};$lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8}
function LeftClick([int]$x,[int]$y){[V17N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V17N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V17N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function Stop-Process {[CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject,[string[]]$Name,[int[]]$Id,[switch]$Force)process{}}
. ./scripts/xg-top5-rollout-submenu-probe.ps1
Remove-Item Function:\Stop-Process -Force

$report="$env:GITHUB_WORKSPACE\xg-top5-v17-report.txt"
'XG Top5 Rollout v17 Real Run'|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$subs=@();foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$subs+=,$e}}catch{}}
if($subs.Count-ne1){throw "Expected one Rollout submenu, got $($subs.Count)"}
$sub=$subs[0];$sr=$sub.Current.BoundingRectangle
$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$preset=@();foreach($e in $desc){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 18'){$preset+=,$e}}catch{}}
if($preset.Count-ne1){throw "Expected Item 18 once, got $($preset.Count)"}
$pr=$preset[0].Current.BoundingRectangle;$delta=[int]($pr.Y-$sr.Y)
if($delta-lt55 -or $delta-gt70){throw "Preset geometry mismatch delta=$delta"}
LeftClick ([int]($pr.X+$pr.Width/2)) ([int]($pr.Y+$pr.Height/2))
Post 'xg-top5-v17/preset-clicked' 'success' '3-ply XG Roller preset clicked'
Start-Sleep 1
Shot 'xg-top5-v17-prompt';DumpUI 'xg-top5-v17-prompt' $xg.Id

$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$dialogs=@();foreach($e in $all){try{if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'TPromptRollOutDlg'){$dialogs+=,$e}}catch{}}
if($dialogs.Count-ne1){throw "Expected TPromptRollOutDlg once, got $($dialogs.Count)"}
$dialog=$dialogs[0]
$children=$dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$oks=@();$games=@()
foreach($e in $children){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'Ok'){$oks+=,$e};if($e.Current.Name-eq'1296'){$games+=,$e}}catch{}}
if($oks.Count-ne1){throw "Expected Ok once, got $($oks.Count)"}
if($games.Count-ne1){throw "Expected 1296 games field once, got $($games.Count)"}
$or=$oks[0].Current.BoundingRectangle
LeftClick ([int]($or.X+$or.Width/2)) ([int]($or.Y+$or.Height/2))
'ROLLOUT_OK_CLICKED: True'|Out-File $report -Append
'ROLLOUT_GAMES: 1296'|Out-File $report -Append
'ROLLOUT_PRESET: Moves 3-ply, cube decisions XG Roller'|Out-File $report -Append
Post 'xg-top5-v17/rollout-started' 'success' 'OK clicked: 1296 games, 3-ply / XG Roller'

$checkpoints=@(2,15,60,180)
$elapsed=0
foreach($target in $checkpoints){
  $sleep=$target-$elapsed;if($sleep-gt0){Start-Sleep $sleep};$elapsed=$target
  $xg.Refresh()
  "CHECKPOINT_${target}S_RESPONDING: $($xg.Responding)"|Out-File $report -Append
  Shot "xg-top5-v17-${target}s";DumpUI "xg-top5-v17-${target}s" $xg.Id
  $allNow=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $nonMain=@();foreach($e in $allNow){try{if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Window -and $e.Current.ClassName-ne'TMainX'){$nonMain+=,$e}}catch{}}
  "CHECKPOINT_${target}S_NON_MAIN_WINDOWS: $($nonMain.Count)"|Out-File $report -Append
  foreach($w in $nonMain){try{"  WINDOW Name=[$($w.Current.Name)] Class=[$($w.Current.ClassName)] Enabled=[$($w.Current.IsEnabled)]"|Out-File $report -Append}catch{}}
}
Post 'xg-top5-v17/checkpoints-captured' 'success' 'Real rollout checkpoints through 180s captured'
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
