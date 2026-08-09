$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class V23N {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
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
function ExportText($xg){
  $xg.Refresh();[V23N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null;Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^c');Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
function DismissSaveGameNow(){
  $dialog=[V23N]::FindExact('Save Game')
  if($dialog-eq[IntPtr]::Zero){return $false}
  $noButton=[V23N]::FindButtonExact($dialog,'No')
  if($noButton-ne[IntPtr]::Zero){
    [V23N]::SendMessage($noButton,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null
    Start-Sleep -Milliseconds 900
    if([V23N]::FindExact('Save Game')-eq[IntPtr]::Zero){return $true}
  }
  [V23N]::SetForegroundWindow($dialog)|Out-Null;Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('%n');Start-Sleep -Milliseconds 900
  return ([V23N]::FindExact('Save Game')-eq[IntPtr]::Zero)
}
function InvokeAnalyzePosition([IntPtr]$hwnd){
  $main=[V23N]::GetMenu($hwnd);$analyze=[V23N]::GetSubMenu($main,4);$positionId=[V23N]::GetMenuItemID($analyze,1)
  if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position unavailable'}
  [V23N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
  [void][V23N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
}

if(-not$env:POSITION_ID){throw 'POSITION_ID is required'}
if(-not$env:POSITION_XGID){throw 'POSITION_XGID is required'}
$positionId=$env:POSITION_ID
$target=$env:POSITION_XGID.Trim()
if($target-notlike'XGID=*'){throw 'POSITION_XGID must start with XGID='}
$expectedPayload=$target.Substring(5)
$prefix="xg-v23-$positionId"
$report=Join-Path $env:GITHUB_WORKSPACE "$prefix-report.txt"
"POSITION_ID: $positionId"|Out-File $report
"POSITION_XGID: $target"|Out-File $report -Append
'SCOPE: non-pristine development dice variant'|Out-File $report -Append

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh();if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready before variant load'}
$hwnd=[IntPtr]$xg.MainWindowHandle
Set-Clipboard -Value $target
Start-Sleep -Milliseconds 250
if((Get-Clipboard -Raw).Trim()-ne$target){throw 'target XGID clipboard verification failed'}
[V23N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep 5
$xg.Refresh();if($xg.MainWindowTitle-notlike'*Position.xgp*'){Shot "$prefix-load-mismatch";throw 'variant XGID did not load as Position.xgp'}
'POSITION_LOAD_SENT: True'|Out-File $report -Append

InvokeAnalyzePosition $hwnd
$elapsed=0;$dismissed=$false;$analysis=$null;$raw=''
while($elapsed-lt120 -and $null-eq$analysis){
  Start-Sleep 2;$elapsed+=2;$xg.Refresh()
  if($xg.HasExited){throw 'XG exited during variant analysis'}
  if(DismissSaveGameNow){
    $dismissed=$true
    "SAVE_GAME_DISMISSED_AT_SECONDS: $elapsed"|Out-File $report -Append
    InvokeAnalyzePosition $hwnd
    continue
  }
  if(-not$xg.Responding){continue}
  try{$candidateText=ExportText $xg}catch{continue}
  if($candidateText.Length-lt100 -or $candidateText-notmatch'(?m)^\s*1\.'){continue}
  $txt=Join-Path $env:GITHUB_WORKSPACE "$prefix-analysis.txt"
  $json=Join-Path $env:GITHUB_WORKSPACE "$prefix-analysis.json"
  Set-Content $txt $candidateText -Encoding UTF8
  & python "$env:GITHUB_WORKSPACE\scripts\parse_xg_position_export.py" $txt $json|Out-Null
  if($LASTEXITCODE-ne0){continue}
  $probe=Get-Content $json -Raw|ConvertFrom-Json
  if([string]$probe.xgid_payload-ne$expectedPayload){continue}
  $analysis=$probe;$raw=$candidateText
}
if($null-eq$analysis){Shot "$prefix-analysis-timeout";throw "variant analysis did not become parseable within ${elapsed}s"}
"ANALYSIS_READY_SECONDS: $elapsed"|Out-File $report -Append
"SAVE_GAME_DISMISSED: $dismissed"|Out-File $report -Append
if($analysis.candidate_count-lt2){throw 'variant analysis returned fewer than two candidates'}
$best=$analysis.candidates[0];$second=$analysis.candidates[1]
$gap=[math]::Round([double]$best.equity-[double]$second.equity,6)
$bookHit=$false
foreach($c in $analysis.candidates){if(([string]$c.source)-like'Book*'){$bookHit=$true}}
$summary=[ordered]@{
  schema='mzand.xg.hard-position-scan.v1'
  scope='non-pristine development dice variant'
  position_id=$positionId
  xgid=$analysis.xgid
  candidate_count=[int]$analysis.candidate_count
  best_move=[string]$best.move
  best_equity=[double]$best.equity
  second_move=[string]$second.move
  second_equity=[double]$second.equity
  top1_gap=$gap
  book_hit=$bookHit
  analysis_elapsed_seconds=$elapsed
  save_game_dismissed=$dismissed
  candidates=$analysis.candidates
}
$summary|ConvertTo-Json -Depth 12|Set-Content (Join-Path $env:GITHUB_WORKSPACE "$prefix-summary.json") -Encoding UTF8
"BEST_MOVE: $($best.move)"|Out-File $report -Append
"SECOND_MOVE: $($second.move)"|Out-File $report -Append
"TOP1_GAP: $gap"|Out-File $report -Append
"BOOK_HIT: $bookHit"|Out-File $report -Append
Shot "$prefix-analysis-ready"
Post "xg-v23/$positionId" 'success' "gap=$gap book=$bookHit candidates=$($analysis.candidate_count)"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
