$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V13N {
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
  [V13N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V13N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V13N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}

# Reuse the proven v8 path to analyze the position, select exactly the first five rows,
# right-click them, and hover Rollout. Suppress only its final process cleanup.
function Stop-Process {
  [CmdletBinding()]
  param(
    [Parameter(ValueFromPipeline=$true)]$InputObject,
    [string[]]$Name,
    [int[]]$Id,
    [switch]$Force
  )
  process { }
}
. ./scripts/xg-top5-rollout-submenu-probe.ps1
Remove-Item Function:\Stop-Process -Force

$report="$env:GITHUB_WORKSPACE\xg-top5-v13-report.txt"
'XG Top5 Rollout v13 Exact Start Probe'|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
if($xg.HasExited){throw 'XG exited before exact Start probe'}
$hwnd=[IntPtr]$xg.MainWindowHandle
if($hwnd-eq[IntPtr]::Zero){throw 'XG main window handle missing before exact Start probe'}
"XG_PID: $($xg.Id)"|Out-File $report -Append
"XG_HANDLE: $hwnd"|Out-File $report -Append
Post 'xg-top5-v13/xg-alive' 'success' 'XG alive after selecting top five'

$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$subs=@()
foreach($e in $all){
  try{
    $r=$e.Current.BoundingRectangle
    if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$subs+=,$e}
  }catch{}
}
if($subs.Count-ne1){Shot 'xg-top5-v13-submenu-mismatch';DumpUI 'xg-top5-v13-submenu-mismatch' $xg.Id;throw "Expected one Rollout submenu, got $($subs.Count)"}
$sub=$subs[0];$sr=$sub.Current.BoundingRectangle
"ROLLOUT_SUBMENU_RECT: $($sr.X),$($sr.Y),$($sr.Width),$($sr.Height)"|Out-File $report -Append

$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$startCandidates=@()
foreach($e in $desc){
  try{
    if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 28'){$startCandidates+=,$e}
  }catch{}
}
if($startCandidates.Count-ne1){Shot 'xg-top5-v13-start-id-mismatch';DumpUI 'xg-top5-v13-start-id-mismatch' $xg.Id;throw "Expected exact Start AutomationId Item 28 once, got $($startCandidates.Count)"}
$startItem=$startCandidates[0]
$rr=$startItem.Current.BoundingRectangle
$delta=[int]($rr.Y-$sr.Y)
"START_AUTOMATION_ID: $($startItem.Current.AutomationId)"|Out-File $report -Append
"START_ITEM_RECT: $($rr.X),$($rr.Y),$($rr.Width),$($rr.Height)"|Out-File $report -Append
"START_ITEM_Y_DELTA: $delta"|Out-File $report -Append
if($rr.Width-lt300 -or $rr.Height-lt15 -or $delta-lt245 -or $delta-gt260){Shot 'xg-top5-v13-start-geometry-mismatch';DumpUI 'xg-top5-v13-start-geometry-mismatch' $xg.Id;throw "Start geometry mismatch delta=$delta"}

$cx=[int]($rr.X+$rr.Width/2);$cy=[int]($rr.Y+$rr.Height/2)
LeftClick $cx $cy
'ROLLOUT_START_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v13/start-clicked' 'success' "Exact Rollout Start Item 28 clicked at $cx,$cy"

Start-Sleep -Milliseconds 900
Shot 'xg-top5-v13-after-start-1s';DumpUI 'xg-top5-v13-after-start-1s' $xg.Id
Start-Sleep 3
$xg.Refresh()
Shot 'xg-top5-v13-after-start-4s';DumpUI 'xg-top5-v13-after-start-4s' $xg.Id
"XG_RESPONDING_4S: $($xg.Responding)"|Out-File $report -Append
"TITLE_AFTER_START: $($xg.MainWindowTitle)"|Out-File $report -Append

$tops=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$dialogs=@()
foreach($e in $tops){
  try{
    if($e.Current.ProcessId-eq$xg.Id -and [IntPtr]$e.Current.NativeWindowHandle-ne$hwnd){$dialogs+=,$e}
  }catch{}
}
"POST_START_DIALOG_CANDIDATES: $($dialogs.Count)"|Out-File $report -Append
foreach($d in $dialogs){
  try{
    $r=$d.Current.BoundingRectangle
    "DIALOG: Name=[$($d.Current.Name)] Class=[$($d.Current.ClassName)] Enabled=[$($d.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]"|Out-File $report -Append
  }catch{}
}
Post 'xg-top5-v13/post-start-captured' 'success' "Exact Start next state captured; dialogs=$($dialogs.Count)"
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
