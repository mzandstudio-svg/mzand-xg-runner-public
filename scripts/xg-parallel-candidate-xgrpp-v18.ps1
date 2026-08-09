$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V18N {
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
  [V18N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V18N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V18N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function RightClick([int]$x,[int]$y){
  [V18N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V18N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V18N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
}
function ExportText($xg){
  $xg.Refresh();[V18N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null;Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^c');Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
function ParseExport([string]$text,[string]$stem){
  $txt=Join-Path $env:GITHUB_WORKSPACE "$stem.txt";$json=Join-Path $env:GITHUB_WORKSPACE "$stem.json"
  Set-Content $txt $text -Encoding UTF8
  & python "$env:GITHUB_WORKSPACE\scripts\parse_xg_position_export.py" $txt $json|Out-Null
  if($LASTEXITCODE-ne0){throw "parse failed for $stem"}
  return (Get-Content $json -Raw|ConvertFrom-Json)
}
function SaveScreeningRecord($parsed,$candidate,[int]$rank,[int]$elapsed,[string]$method,[bool]$reused,[string]$path){
  $record=[ordered]@{
    schema='mzand.xg.screening-candidate.v1';xgid=$parsed.xgid;xgid_payload=$parsed.xgid_payload;
    original_analysis_rank=$rank;screening_method=$method;reused_existing=$reused;elapsed_seconds=$elapsed;
    candidate=$candidate;score=$parsed.score;cube=$parsed.cube;on_roll=$parsed.on_roll;dice=$parsed.dice;xg_version=$parsed.xg_version
  }
  $record|ConvertTo-Json -Depth 12|Set-Content $path -Encoding UTF8
}

$rank=[int]$env:CANDIDATE_RANK
if($rank-lt1 -or $rank-gt5){throw "rank must be 1..5, got $rank"}
$prefix="xg-v18-candidate-$rank"
$report=Join-Path $env:GITHUB_WORKSPACE "$prefix-report.txt"
$outJson=Join-Path $env:GITHUB_WORKSPACE "$prefix-xgrpp.json"
"XG Screening v18 rank=$rank"|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh();if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
$hwnd=[IntPtr]$xg.MainWindowHandle

$main=[V18N]::GetMenu($hwnd);$analyze=[V18N]::GetSubMenu($main,4);$positionId=[V18N]::GetMenuItemID($analyze,1)
if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position unavailable'}
[V18N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
[void][V18N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Start-Sleep 15
$baselineText=ExportText $xg
$baseline=ParseExport $baselineText "$prefix-baseline"
$target=$baseline.candidates|Where-Object{$_.rank-eq$rank}|Select-Object -First 1
if($null-eq$target){throw "baseline missing rank $rank"}
$targetMove=[string]$target.move
$baselineMethod=[string]$target.analysis_method
"TARGET_MOVE: $targetMove"|Out-File $report -Append
"BASELINE_SOURCE: $($target.source)"|Out-File $report -Append
"BASELINE_METHOD: $baselineMethod"|Out-File $report -Append
"BASELINE_EQUITY: $($target.equity)"|Out-File $report -Append
Post "$prefix/target" 'success' "candidate rank $rank identified"

# Screening priority: completed deep Rollout >=1296 > existing XG Roller++ > fresh XG Roller++.
$reuse=$false
$reuseMethod=''
if($baselineMethod-eq'Rollout'){
  $prov=[string]$target.provenance
  $m=[regex]::Match($prov,'(?i)\b(\d+)\s+Games rolled\b')
  if($m.Success -and [int]$m.Groups[1].Value-ge1296){$reuse=$true;$reuseMethod='Rollout'}
}elseif($baselineMethod-eq'XG Roller++'){
  $reuse=$true;$reuseMethod='XG Roller++'
}
if($reuse){
  "REUSED_EXISTING: True"|Out-File $report -Append
  "SCREENING_METHOD: $reuseMethod"|Out-File $report -Append
  SaveScreeningRecord $baseline $target $rank 0 $reuseMethod $true $outJson
  Post "$prefix/complete" 'success' "reused existing screening method for rank $rank"
  Shot "$prefix-reused-final"
  Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
  exit 0
}

$wr=New-Object V18N+RECT
if(-not[V18N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$width=$wr.Right-$wr.Left;$height=$wr.Bottom-$wr.Top
if($width-ne924 -or $height-ne668){throw "unexpected XG geometry ${width}x${height}"}
$rowX=[int]$wr.Left+130;$rowY=[int]$wr.Top+370+(43*($rank-1))
LeftClick $rowX $rowY;Start-Sleep -Milliseconds 250;RightClick $rowX $rowY;Start-Sleep -Milliseconds 700

$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$menus=@()
foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt200 -and $r.Width-lt270 -and $r.Height-gt400 -and $r.Height-lt450){$menus+=,$e}}catch{}}
if($menus.Count-ne1){Shot "$prefix-context-mismatch";throw "expected one move context menu, got $($menus.Count)"}
$cr=$menus[0].Current.BoundingRectangle
"CONTEXT_RECT: $($cr.X),$($cr.Y),$($cr.Width),$($cr.Height)"|Out-File $report -Append
# Verified on independent context screenshots: XG Roller++ row center is ~203px below context top.
$xgrX=[int]($cr.X+$cr.Width/2);$xgrY=[int]($cr.Y+203)
"XGRPP_GEOMETRY_CLICK: $xgrX,$xgrY"|Out-File $report -Append
Shot "$prefix-context-before-xgrpp"
LeftClick $xgrX $xgrY
Post "$prefix/started" 'success' 'fresh XG Roller++ command clicked at verified context geometry'
Start-Sleep 2

$complete=$false;$elapsed=0;$finalParsed=$null;$finalText=''
while($elapsed-lt600 -and -not$complete){
  Start-Sleep 10;$elapsed+=10;$xg.Refresh()
  if($xg.HasExited){throw 'XG exited during XG Roller++'}
  if($elapsed-in@(10,30,60,120,300,600)){Shot "$prefix-running-${elapsed}s"}
  if(-not$xg.Responding){"T=${elapsed}s RESPONDING=False"|Out-File $report -Append;continue}
  try{
    $text=ExportText $xg
    if($text.Length-lt100){continue}
    $parsed=ParseExport $text "$prefix-poll"
    $hit=$parsed.candidates|Where-Object{$_.move-eq$targetMove -and $_.analysis_method-eq'XG Roller++'}|Select-Object -First 1
    if($null-ne$hit){$complete=$true;$finalText=$text;$finalParsed=$parsed;break}
    "T=${elapsed}s TARGET_METHOD_PENDING"|Out-File $report -Append
  }catch{"T=${elapsed}s PARSE_PENDING=$($_.Exception.Message)"|Out-File $report -Append}
}
if(-not$complete){Shot "$prefix-timeout";throw "XG Roller++ not exported for target rank $rank within 600 seconds"}
$final=($finalParsed.candidates|Where-Object{$_.move-eq$targetMove -and $_.analysis_method-eq'XG Roller++'}|Select-Object -First 1)
Set-Content (Join-Path $env:GITHUB_WORKSPACE "$prefix-final.txt") $finalText -Encoding UTF8
SaveScreeningRecord $finalParsed $final $rank $elapsed 'XG Roller++' $false $outJson
"XGRPP_COMPLETE: True"|Out-File $report -Append
"REUSED_EXISTING: False"|Out-File $report -Append
"ELAPSED_SECONDS: $elapsed"|Out-File $report -Append
"XGRPP_EQUITY: $($final.equity)"|Out-File $report -Append
Post "$prefix/complete" 'success' "fresh XG Roller++ export complete for rank $rank in ${elapsed}s"
Shot "$prefix-final"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
