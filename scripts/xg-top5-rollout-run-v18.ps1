$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V18N {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function Post([string]$context,[string]$state,[string]$description){try{$payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress;$headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'};Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null}catch{}}
function Shot([string]$name){$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save("$env:GITHUB_WORKSPACE\$name.png",[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}
function DumpUI([string]$name,[int]$processId){$root=[System.Windows.Automation.AutomationElement]::RootElement;$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition);$lines=New-Object 'System.Collections.Generic.List[string]';foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$processId -or $e.Current.ClassName-eq'#32768' -or $e.Current.ClassName-eq'#32770'){$lines.Add("PID=[$($e.Current.ProcessId)] Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")}}catch{}};$lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8}
function LeftClick([int]$x,[int]$y){[V18N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V18N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V18N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function ProgressSnapshot($root,[int]$processId){
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $rows=@()
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-eq$processId -and $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::ProgressBar){
        $r=$e.Current.BoundingRectangle
        $value=$null;$min=$null;$max=$null
        try{$p=$e.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern);$value=[double]$p.Current.Value;$min=[double]$p.Current.Minimum;$max=[double]$p.Current.Maximum}catch{}
        $rows += [pscustomobject]@{Id=$e.Current.AutomationId;Class=$e.Current.ClassName;X=$r.X;Y=$r.Y;W=$r.Width;H=$r.Height;Value=$value;Minimum=$min;Maximum=$max}
      }
    }catch{}
  }
  return @($rows)
}

# Reuse the proven helper to Analyze Position, select exactly the first five rows,
# right-click the selection and hover the Rollout submenu. Preserve XG afterwards.
function Stop-Process {[CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject,[string[]]$Name,[int[]]$Id,[switch]$Force)process{}}
. ./scripts/xg-top5-rollout-submenu-probe.ps1
Remove-Item Function:\Stop-Process -Force

$report="$env:GITHUB_WORKSPACE\xg-top5-v18-report.txt"
'XG Top5 Rollout v18 Complete Run'|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$root=[System.Windows.Automation.AutomationElement]::RootElement

# Explicitly choose the proven preset Item 18 = Moves 3-ply, cube decisions XG Roller.
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$subs=@();foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$subs+=,$e}}catch{}}
if($subs.Count-ne1){throw "Expected one Rollout submenu, got $($subs.Count)"}
$sub=$subs[0];$sr=$sub.Current.BoundingRectangle
$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$preset=@();foreach($e in $desc){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 18'){$preset+=,$e}}catch{}}
if($preset.Count-ne1){throw "Expected preset Item 18 once, got $($preset.Count)"}
$pr=$preset[0].Current.BoundingRectangle;$delta=[int]($pr.Y-$sr.Y)
if($delta-lt55 -or $delta-gt70){throw "Preset geometry mismatch delta=$delta"}
LeftClick ([int]($pr.X+$pr.Width/2)) ([int]($pr.Y+$pr.Height/2))
Post 'xg-top5-v18/preset-clicked' 'success' '3-ply XG Roller preset selected'
Start-Sleep 1
Shot 'xg-top5-v18-prompt';DumpUI 'xg-top5-v18-prompt' $xg.Id

# Require the exact duration prompt and exact 1296 field, then click Ok.
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$dialogs=@();foreach($e in $all){try{if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'TPromptRollOutDlg'){$dialogs+=,$e}}catch{}}
if($dialogs.Count-ne1){throw "Expected TPromptRollOutDlg once, got $($dialogs.Count)"}
$children=$dialogs[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$oks=@();$games=@();foreach($e in $children){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'Ok'){$oks+=,$e};if($e.Current.Name-eq'1296'){$games+=,$e}}catch{}}
if($oks.Count-ne1){throw "Expected Ok once, got $($oks.Count)"};if($games.Count-ne1){throw "Expected 1296 once, got $($games.Count)"}
$or=$oks[0].Current.BoundingRectangle;LeftClick ([int]($or.X+$or.Width/2)) ([int]($or.Y+$or.Height/2))
'ROLLOUT_OK_CLICKED: True'|Out-File $report -Append
'ROLLOUT_GAMES: 1296'|Out-File $report -Append
'ROLLOUT_PRESET: Moves 3-ply, cube decisions XG Roller'|Out-File $report -Append
Post 'xg-top5-v18/rollout-started' 'success' '1296-game 3-ply/XG Roller rollout started'

# Poll the two native progress bars until the rollout completes. A completed rollout removes
# active progress movement; RangeValue is used when exposed. Never claim completion on timeout.
$maxSeconds=2100
$interval=30
$elapsed=0
$noBarsStreak=0
$completed=$false
$lastSignature=''
$stableStreak=0
while($elapsed-lt$maxSeconds){
  Start-Sleep $interval;$elapsed+=$interval
  $xg.Refresh();if($xg.HasExited){throw "XG exited during rollout at ${elapsed}s"}
  $bars=ProgressSnapshot $root $xg.Id
  $parts=@()
  foreach($b in $bars){$parts += "Id=$($b.Id),Y=$($b.Y),Value=$($b.Value),Min=$($b.Minimum),Max=$($b.Maximum)"}
  $sig=($parts -join '; ')
  "PROGRESS_${elapsed}S: count=$($bars.Count) $sig"|Out-File $report -Append
  if($bars.Count-eq0){$noBarsStreak++}else{$noBarsStreak=0}
  if($sig-eq$lastSignature -and $sig-ne''){$stableStreak++}else{$stableStreak=0};$lastSignature=$sig

  # Check for an explicit 100% RangeValue where supported.
  $known=@($bars|Where-Object{$null-ne$_.Value -and $null-ne$_.Maximum -and $_.Maximum-gt$_.Minimum})
  if($known.Count-gt0){
    $allDone=$true
    foreach($b in $known){$pct=100.0*($b.Value-$b.Minimum)/($b.Maximum-$b.Minimum);if($pct-lt99.9){$allDone=$false}}
    if($allDone){$completed=$true;"COMPLETION_SIGNAL: progress-bars-100 at ${elapsed}s"|Out-File $report -Append;break}
  }
  if($noBarsStreak-ge3){$completed=$true;"COMPLETION_SIGNAL: progress-bars-absent-3-polls at ${elapsed}s"|Out-File $report -Append;break}

  if(($elapsed%300)-eq0){Shot "xg-top5-v18-${elapsed}s";DumpUI "xg-top5-v18-${elapsed}s" $xg.Id;Post "xg-top5-v18/progress-${elapsed}s" 'pending' "rollout still active at ${elapsed}s"}
}

Start-Sleep 2
$xg.Refresh()
Shot 'xg-top5-v18-final';DumpUI 'xg-top5-v18-final' $xg.Id
"ROLLOUT_COMPLETED: $completed"|Out-File $report -Append
"FINAL_ELAPSED_SECONDS: $elapsed"|Out-File $report -Append
"XG_RESPONDING_FINAL: $($xg.Responding)"|Out-File $report -Append
if($completed){Post 'xg-top5-v18/rollout-completed' 'success' "completion detected at ${elapsed}s"}else{Post 'xg-top5-v18/rollout-completed' 'failure' "no completion signal by ${elapsed}s"}
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
if(-not$completed){throw 'Rollout did not reach a verified completion signal within the polling window'}
