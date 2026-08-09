$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V16N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
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
function LeftClick([int]$x,[int]$y){
  [V16N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V16N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70
  [V16N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function RightClick([int]$x,[int]$y){
  [V16N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V16N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70
  [V16N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
}
function ExportText($xg){
  $xg.Refresh()
  [V16N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^c')
  Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
function ParseExport([string]$text,[string]$stem){
  $txt=Join-Path $env:GITHUB_WORKSPACE "$stem.txt"
  $json=Join-Path $env:GITHUB_WORKSPACE "$stem.json"
  Set-Content $txt $text -Encoding UTF8
  & python "$env:GITHUB_WORKSPACE\scripts\parse_xg_position_export.py" $txt $json | Out-Null
  if($LASTEXITCODE-ne0){throw "parse_xg_position_export.py failed for $stem"}
  return (Get-Content $json -Raw | ConvertFrom-Json)
}
function FindRolloutPrompt([int]$pid){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $hits=@()
  foreach($e in $all){try{if($e.Current.ProcessId-eq$pid -and $e.Current.Name-eq'Rollout' -and $e.Current.ClassName-eq'TPromptRollOutDlg'){$hits+=,$e}}catch{}}
  if($hits.Count-eq1){return $hits[0]}
  return $null
}

$rank=[int]$env:CANDIDATE_RANK
if($rank-lt1 -or $rank-gt5){throw "CANDIDATE_RANK must be 1..5, got $rank"}
$prefix="xg-v16-candidate-$rank"
$report=Join-Path $env:GITHUB_WORKSPACE "$prefix-report.txt"
"XG Parallel Candidate Rollout v16 rank=$rank"|Out-File $report

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
$hwnd=[IntPtr]$xg.MainWindowHandle
$main=[V16N]::GetMenu($hwnd);$analyze=[V16N]::GetSubMenu($main,4);$positionId=[V16N]::GetMenuItemID($analyze,1)
if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position command unavailable'}
[V16N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
[void][V16N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Start-Sleep 15
Post "$prefix/analyzed" 'success' 'Analyze Position completed for candidate selection'

$baselineText=ExportText $xg
$baseline=ParseExport $baselineText "$prefix-baseline"
$target=$baseline.candidates|Where-Object{$_.rank-eq$rank}|Select-Object -First 1
if($null-eq$target){throw "Baseline export missing rank $rank"}
$targetMove=[string]$target.move
"TARGET_MOVE: $targetMove"|Out-File $report -Append
"BASELINE_EQUITY: $($target.equity)"|Out-File $report -Append
Post "$prefix/target" 'success' "rank=$rank move=$targetMove"

$wr=New-Object V16N+RECT
if(-not[V16N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$width=$wr.Right-$wr.Left;$height=$wr.Bottom-$wr.Top
if($width-ne924 -or $height-ne668){throw "Unexpected XG window geometry ${width}x${height}"}
$rowX=[int]$wr.Left+130
$rowY=[int]$wr.Top+370+(43*($rank-1))
LeftClick $rowX $rowY
Start-Sleep -Milliseconds 250
RightClick $rowX $rowY
Start-Sleep -Milliseconds 700

$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$contexts=@()
foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt200 -and $r.Width-lt270 -and $r.Height-gt400){$contexts+=,$e}}catch{}}
if($contexts.Count-ne1){Shot "$prefix-context-mismatch";throw "Expected one move context menu, got $($contexts.Count)"}
$cr=$contexts[0].Current.BoundingRectangle
[V16N]::SetCursorPos([int]($cr.X+$cr.Width/2),[int]($cr.Y+221))|Out-Null
Start-Sleep 1

$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$subs=@()
foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$subs+=,$e}}catch{}}
if($subs.Count-ne1){Shot "$prefix-submenu-mismatch";throw "Expected one Rollout submenu, got $($subs.Count)"}
$sub=$subs[0]
$desc=$sub.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$preset=@()
foreach($e in $desc){try{if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem -and $e.Current.AutomationId-eq'Item 18'){$preset+=,$e}}catch{}}
if($preset.Count-ne1){Shot "$prefix-preset-mismatch";throw "Expected 3-ply/XG Roller preset Item 18 once, got $($preset.Count)"}
$pr=$preset[0].Current.BoundingRectangle
LeftClick ([int]($pr.X+$pr.Width/2)) ([int]($pr.Y+$pr.Height/2))
Start-Sleep 1

$prompt=$null
for($i=0;$i-lt10 -and $null-eq$prompt;$i++){$prompt=FindRolloutPrompt $xg.Id;if($null-eq$prompt){Start-Sleep -Milliseconds 300}}
if($null-eq$prompt){Shot "$prefix-prompt-missing";throw 'Rollout prompt not found after preset click'}
$pdesc=$prompt.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$ok=$null;$games1296=$false
foreach($e in $pdesc){
  try{
    if($e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button -and $e.Current.Name-eq'Ok'){$ok=$e}
    if($e.Current.Name-eq'1296' -and $e.Current.ClassName-eq'TSpinEditX'){$games1296=$true}
  }catch{}
}
if(-not$games1296 -or $null-eq$ok){Shot "$prefix-prompt-invalid";throw 'Verified 1296/Ok controls missing from Rollout prompt'}
Shot "$prefix-before-ok"
$or=$ok.Current.BoundingRectangle
LeftClick ([int]($or.X+$or.Width/2)) ([int]($or.Y+$or.Height/2))
Post "$prefix/started" 'success' "1296-game rollout started for $targetMove"
"ROLLOUT_STARTED: True"|Out-File $report -Append

$complete=$false;$elapsed=0;$lastText='';$lastParsed=$null
while($elapsed-lt1200 -and -not$complete){
  Start-Sleep 15;$elapsed+=15
  $xg.Refresh()
  if($xg.HasExited){throw 'XG exited during rollout'}
  if($elapsed-in@(15,60,180,360,600,900,1200)){Shot "$prefix-running-${elapsed}s"}
  if(-not$xg.Responding){"T=${elapsed}s RESPONDING=False"|Out-File $report -Append;continue}
  try{
    $candidateText=ExportText $xg
    if($candidateText.Length-lt100){"T=${elapsed}s EXPORT_SHORT=$($candidateText.Length)"|Out-File $report -Append;continue}
    $lastText=$candidateText
    $parsed=ParseExport $candidateText "$prefix-poll"
    $lastParsed=$parsed
    $rolled=$parsed.candidates|Where-Object{$_.move-eq$targetMove -and $_.analysis_method-eq'Rollout'}|Select-Object -First 1
    if($null-ne$rolled){
      $prov=[string]$rolled.provenance
      "T=${elapsed}s METHOD=Rollout PROVENANCE=[$prov]"|Out-File $report -Append
      if($prov -match '(?i)\b1296\s+Games rolled\b'){$complete=$true;break}
    }else{
      "T=${elapsed}s METHOD_NOT_FINAL"|Out-File $report -Append
    }
  }catch{
    "T=${elapsed}s EXPORT_PARSE_PENDING=$($_.Exception.Message)"|Out-File $report -Append
  }
}
if(-not$complete){
  if($lastText){Set-Content (Join-Path $env:GITHUB_WORKSPACE "$prefix-last-export.txt") $lastText -Encoding UTF8}
  Shot "$prefix-timeout"
  throw "Candidate rank $rank did not export a completed 1296-game rollout within 1200 seconds"
}

$finalText=ExportText $xg
$finalParsed=ParseExport $finalText "$prefix-final-position"
$finalCandidate=$finalParsed.candidates|Where-Object{$_.move-eq$targetMove -and $_.analysis_method-eq'Rollout'}|Select-Object -First 1
if($null-eq$finalCandidate){throw 'Completed target candidate missing from final parsed export'}
$record=[ordered]@{
  schema='mzand.xg.rollout-candidate.v1'
  xgid=$finalParsed.xgid
  xgid_payload=$finalParsed.xgid_payload
  original_rank=$rank
  rollout_games=1296
  checker_preset='Moves 3-ply'
  cube_preset='XG Roller'
  variance_reduction=$true
  elapsed_seconds=$elapsed
  candidate=$finalCandidate
  score=$finalParsed.score
  cube=$finalParsed.cube
  on_roll=$finalParsed.on_roll
  dice=$finalParsed.dice
  xg_version=$finalParsed.xg_version
}
$record|ConvertTo-Json -Depth 12|Set-Content (Join-Path $env:GITHUB_WORKSPACE "$prefix-rollout.json") -Encoding UTF8
"ROLLOUT_COMPLETE: True"|Out-File $report -Append
"ELAPSED_SECONDS: $elapsed"|Out-File $report -Append
"FINAL_EQUITY: $($finalCandidate.equity)"|Out-File $report -Append
"FINAL_CONFIDENCE_PM: $($finalCandidate.confidence.plus_minus_equity)"|Out-File $report -Append
Post "$prefix/complete" 'success' "completed 1296 games in ${elapsed}s equity=$($finalCandidate.equity)"
Shot "$prefix-final"
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
