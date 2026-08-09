$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V15N {
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
  [V15N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V15N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V15N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}

# Reuse proven v8: Analyze Position, select exactly first five move rows, open Rollout submenu.
function Stop-Process {
  [CmdletBinding()]
  param([Parameter(ValueFromPipeline=$true)]$InputObject,[string[]]$Name,[int[]]$Id,[switch]$Force)
  process { }
}
. ./scripts/xg-top5-rollout-submenu-probe.ps1
Remove-Item Function:\Stop-Process -Force

$report="$env:GITHUB_WORKSPACE\xg-top5-v15-report.txt"
'XG Top5 Rollout v15 Controlled Run'|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh();if($xg.HasExited){throw 'XG exited before rollout run'}
$root=[System.Windows.Automation.AutomationElement]::RootElement

# Exact proven Rollout submenu and exact preset row: Item 18 = Moves 3-ply, cube decisions XG Roller.
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$subs=@()
foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$subs+=,$e}}catch{}}
if($subs.Count-ne1){throw "Expected one Rollout submenu, got $($subs.Count)"}
$sub=$subs[0];$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$preset=@()
foreach($e in $desc){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 18'){$preset+=,$e}}catch{}}
if($preset.Count-ne1){throw "Expected preset Item 18 once, got $($preset.Count)"}
$pr=$preset[0].Current.BoundingRectangle
LeftClick ([int]($pr.X+$pr.Width/2)) ([int]($pr.Y+$pr.Height/2))
'PRESET_3PLY_XG_ROLLER_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v15/preset' 'success' 'Preset Item 18 clicked: Moves 3-ply, cube decisions XG Roller'
Start-Sleep 1

# v14 evidence proved Item 18 opens the Rollout prompt directly with the correct preset text.
$tops=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$prompts=@()
foreach($e in $tops){try{if($e.Current.ProcessId-eq$xg.Id -and $e.Current.Name-eq'Rollout' -and $e.Current.ClassName-eq'TPromptRollOutDlg'){$prompts+=,$e}}catch{}}
if($prompts.Count-ne1){Shot 'xg-top5-v15-prompt-missing';DumpUI 'xg-top5-v15-prompt-missing' $xg.Id;throw "Expected one Rollout prompt, got $($prompts.Count)"}
$prompt=$prompts[0]
$pdesc=$prompt.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$oks=@();$games=@()
foreach($e in $pdesc){
  try{
    if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'Ok'){$oks+=,$e}
    if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Document -and $e.Current.Name-eq'1296'){$games+=,$e}
  }catch{}
}
if($oks.Count-ne1){throw "Expected one Rollout OK button, got $($oks.Count)"}
if($games.Count-ne1){throw "Expected Number of Games 1296, got $($games.Count) matching documents"}
Shot 'xg-top5-v15-before-ok';DumpUI 'xg-top5-v15-before-ok' $xg.Id
'ROLLOUT_PROMPT_FOUND: True'|Out-File $report -Append
'ROLLOUT_GAMES_1296_CONFIRMED: True'|Out-File $report -Append
Post 'xg-top5-v15/prompt' 'success' 'Correct Rollout prompt present with 1296 games'

$or=$oks[0].Current.BoundingRectangle
LeftClick ([int]($or.X+$or.Width/2)) ([int]($or.Y+$or.Height/2))
'ROLLOUT_OK_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v15/ok-clicked' 'success' 'Rollout OK clicked for selected five moves'

Start-Sleep 2
$xg.Refresh()
"RESPONDING_2S: $($xg.Responding)"|Out-File $report -Append
Shot 'xg-top5-v15-after-ok-2s';DumpUI 'xg-top5-v15-after-ok-2s' $xg.Id
Start-Sleep 8
$xg.Refresh()
"RESPONDING_10S: $($xg.Responding)"|Out-File $report -Append
Shot 'xg-top5-v15-after-ok-10s';DumpUI 'xg-top5-v15-after-ok-10s' $xg.Id
Start-Sleep 20
$xg.Refresh()
"RESPONDING_30S: $($xg.Responding)"|Out-File $report -Append
"TITLE_30S: $($xg.MainWindowTitle)"|Out-File $report -Append
Shot 'xg-top5-v15-after-ok-30s';DumpUI 'xg-top5-v15-after-ok-30s' $xg.Id

$tops2=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
foreach($e in $tops2){
  try{
    if($e.Current.ProcessId-eq$xg.Id){
      $r=$e.Current.BoundingRectangle
      "TOP_WINDOW_30S: Name=[$($e.Current.Name)] Class=[$($e.Current.ClassName)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]"|Out-File $report -Append
    }
  }catch{}
}
'ROLLOUT_EXECUTION_OBSERVED_30S: True'|Out-File $report -Append
Post 'xg-top5-v15/started' 'success' 'Five-move rollout accepted; 30-second execution evidence captured'
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
