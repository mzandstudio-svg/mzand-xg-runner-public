$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class V22N {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int maxCount);
  static string Text(IntPtr hWnd) { var b=new StringBuilder(512); GetWindowText(hWnd,b,b.Capacity); return b.ToString(); }
  static string ClassName(IntPtr hWnd) { var b=new StringBuilder(256); GetClassName(hWnd,b,b.Capacity); return b.ToString(); }
  public static IntPtr FindExact(string text) {
    IntPtr found=IntPtr.Zero;
    EnumProc top=(h,l)=> {
      if(Text(h)==text){found=h;return false;}
      EnumProc child=(c,cl)=> { if(Text(c)==text){found=c;return false;} return true; };
      EnumChildWindows(h,child,IntPtr.Zero);
      return found==IntPtr.Zero;
    };
    EnumWindows(top,IntPtr.Zero);
    return found;
  }
  public static IntPtr FindButtonExact(IntPtr parent,string text) {
    IntPtr found=IntPtr.Zero;
    EnumProc child=(h,l)=> { if(Text(h)==text && ClassName(h)=="Button"){found=h;return false;} return true; };
    EnumChildWindows(parent,child,IntPtr.Zero);
    return found;
  }
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
  $bmp.Save((Join-Path $env:GITHUB_WORKSPACE "$name.png"),[System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose();$bmp.Dispose()
}
function LeftClick([int]$x,[int]$y){
  [V22N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V22N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V22N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function RightClick([int]$x,[int]$y){
  [V22N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120
  [V22N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V22N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
}
function ExportText($xg){
  $xg.Refresh();[V22N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null;Start-Sleep -Milliseconds 250
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
function DismissSaveGameNow(){
  $dialog=[V22N]::FindExact('Save Game')
  if($dialog-eq[IntPtr]::Zero){return $false}
  $noButton=[V22N]::FindButtonExact($dialog,'No')
  if($noButton-ne[IntPtr]::Zero){
    [V22N]::SendMessage($noButton,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null
    Start-Sleep -Milliseconds 900
    if([V22N]::FindExact('Save Game')-eq[IntPtr]::Zero){return $true}
  }
  [V22N]::SetForegroundWindow($dialog)|Out-Null;Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('%n');Start-Sleep -Milliseconds 900
  return ([V22N]::FindExact('Save Game')-eq[IntPtr]::Zero)
}
function InvokeAnalyzePosition([IntPtr]$hwnd){
  $main=[V22N]::GetMenu($hwnd);$analyze=[V22N]::GetSubMenu($main,4);$positionId=[V22N]::GetMenuItemID($analyze,1)
  if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position unavailable'}
  [V22N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
  [void][V22N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
}

$report=Join-Path $env:GITHUB_WORKSPACE 'xg-v22-raw-probe-report.txt'
'XG post-XGR++ raw export probe v22'|Out-File $report
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh();if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
$hwnd=[IntPtr]$xg.MainWindowHandle
InvokeAnalyzePosition $hwnd
$baseline=$null;$baselineText='';$elapsed=0;$dismissed=$false
while($elapsed-lt180 -and $null-eq$baseline){
  Start-Sleep 2;$elapsed+=2;$xg.Refresh()
  if(DismissSaveGameNow){
    $dismissed=$true
    "SAVE_GAME_DISMISSED_AT_SECONDS: $elapsed"|Out-File $report -Append
    InvokeAnalyzePosition $hwnd
    continue
  }
  if(-not$xg.Responding){continue}
  try{
    $text=ExportText $xg
    if($text.Length-lt100){continue}
    $parsed=ParseExport $text 'xg-v22-baseline'
    if([string]$parsed.xgid_payload-ne'-a---BDBBA--dBb--c-dBa----:1:-1:-1:64:6:16:0:19:10'){continue}
    $baselineText=$text;$baseline=$parsed
  }catch{}
}
if($null-eq$baseline){Shot 'xg-v22-baseline-timeout';throw 'Baseline analysis did not become parseable'}
"BASELINE_READY_SECONDS: $elapsed"|Out-File $report -Append
"SAVE_GAME_DISMISSED: $dismissed"|Out-File $report -Append
$target=$baseline.candidates|Where-Object{$_.rank-eq1}|Select-Object -First 1
if($null-eq$target){throw 'Baseline rank 1 missing'}
"TARGET_MOVE: $($target.move)"|Out-File $report -Append
"TARGET_SOURCE: $($target.source)"|Out-File $report -Append
"TARGET_EQUITY: $($target.equity)"|Out-File $report -Append

$wr=New-Object V22N+RECT
if(-not[V22N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$width=$wr.Right-$wr.Left;$height=$wr.Bottom-$wr.Top
if($width-ne924 -or $height-ne668){throw "unexpected XG geometry ${width}x${height}"}
$rowX=[int]$wr.Left+130;$rowY=[int]$wr.Top+370
LeftClick $rowX $rowY;Start-Sleep -Milliseconds 250;RightClick $rowX $rowY;Start-Sleep -Milliseconds 700
Shot 'xg-v22-context-before-xgrpp'
# Geometry proven by earlier controlled XGR++ and v21 runs.
$xgrX=[int]$wr.Left+294;$xgrY=[int]$wr.Top+499
# Use context-relative geometry from the stable 924x668 window: menu click point is 294,499 in screen coordinates when window origin is 0,0.
$xgrX=[int]$wr.Left+294;$xgrY=[int]$wr.Top+499
"XGRPP_CLICK_POINT: $xgrX,$xgrY"|Out-File $report -Append
LeftClick $xgrX $xgrY
Post 'xg-v22/xgrpp-started' 'success' 'XG Roller++ clicked for rank 1 raw export probe'
Start-Sleep 10
$raw10=ExportText $xg
Set-Content (Join-Path $env:GITHUB_WORKSPACE 'xg-v22-after-xgrpp-10s.txt') $raw10 -Encoding UTF8
"RAW_10S_LENGTH: $($raw10.Length)"|Out-File $report -Append
Shot 'xg-v22-after-xgrpp-10s'
Start-Sleep 20
$raw30=ExportText $xg
Set-Content (Join-Path $env:GITHUB_WORKSPACE 'xg-v22-after-xgrpp-30s.txt') $raw30 -Encoding UTF8
"RAW_30S_LENGTH: $($raw30.Length)"|Out-File $report -Append
$rankLines=($raw30 -split "`r?`n")|Where-Object{$_ -match '^\s*\d+\.'}
$rankLines|Set-Content (Join-Path $env:GITHUB_WORKSPACE 'xg-v22-after-xgrpp-rank-lines.txt') -Encoding UTF8
"RANK_LINE_COUNT: $($rankLines.Count)"|Out-File $report -Append
Shot 'xg-v22-after-xgrpp-30s'
Post 'xg-v22/raw-captured' 'success' "raw exports captured; rank lines=$($rankLines.Count)"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
