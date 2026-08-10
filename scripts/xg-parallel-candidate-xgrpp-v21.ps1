$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-xgrpp-v18.ps1'
$src=Get-Content $srcPath -Raw

$old=@'
Start-Sleep 15
$baselineText=ExportText $xg
$baseline=ParseExport $baselineText "$prefix-baseline"
'@
$new=@'
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class V21Save {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
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
function DismissSaveGameNow(){
  $dialog=[V21Save]::FindExact('Save Game')
  if($dialog-eq[IntPtr]::Zero){return $false}
  $noButton=[V21Save]::FindButtonExact($dialog,'No')
  if($noButton-ne[IntPtr]::Zero){
    [V21Save]::SendMessage($noButton,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null
    Start-Sleep -Milliseconds 900
    if([V21Save]::FindExact('Save Game')-eq[IntPtr]::Zero){return $true}
  }
  [V21Save]::SetForegroundWindow($dialog)|Out-Null
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('%n')
  Start-Sleep -Milliseconds 900
  return ([V21Save]::FindExact('Save Game')-eq[IntPtr]::Zero)
}
function ReissueMidgameAnalysis(){
  $main=[V18N]::GetMenu($hwnd);$analyze=[V18N]::GetSubMenu($main,4);$positionId=[V18N]::GetMenuItemID($analyze,1)
  [V18N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
  [void][V18N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
}
$savePromptSeen=$false
$savePromptDismissed=$false
$reissueCount=0
$expectedPayload='-a---BDBBA--dBb--c-dBa----:1:-1:-1:64:6:16:0:19:10'
$baselineText='';$baseline=$null;$analysisReady=$false;$analysisElapsed=0
while($analysisElapsed-lt240 -and -not$analysisReady){
  Start-Sleep 2;$analysisElapsed+=2;$xg.Refresh()
  if($xg.HasExited){throw 'XG exited during Analyze Position'}
  if(DismissSaveGameNow){
    $savePromptSeen=$true;$savePromptDismissed=$true;$reissueCount++
    "SAVE_GAME_PROMPT_DISMISSED_AT_SECONDS: $analysisElapsed"|Out-File $report -Append
    Post "$prefix/save-dismissed" 'success' "Save Game dismissed at ${analysisElapsed}s"
    if($reissueCount-gt3){Shot "$prefix-save-prompt-loop";throw 'Save Game prompt repeated more than three times'}
    ReissueMidgameAnalysis
    "ANALYZE_REISSUED_AFTER_SAVE_PROMPT: $reissueCount"|Out-File $report -Append
    continue
  }
  if(-not$xg.Responding){continue}
  try{$candidateText=ExportText $xg}catch{continue}
  if($candidateText.Length-le100 -or $candidateText-notmatch'(?m)^\s*1\.' -or $candidateText-notmatch'(?i)eq:[+-]\d+\.\d+'){continue}
  try{$probe=ParseExport $candidateText "$prefix-baseline-probe"}catch{continue}
  if([string]$probe.xgid_payload-ne$expectedPayload){
    "BASELINE_XGID_MISMATCH_AT_SECONDS: $analysisElapsed"|Out-File $report -Append
    $reissueCount++
    if($reissueCount-gt3){Shot "$prefix-xgid-mismatch";throw "Analyze Position stayed on unexpected XGID [$($probe.xgid_payload)]"}
    ReissueMidgameAnalysis
    continue
  }
  $baselineText=$candidateText;$baseline=$probe;$analysisReady=$true
}
"SAVE_GAME_PROMPT_SEEN: $savePromptSeen"|Out-File $report -Append
"SAVE_GAME_PROMPT_DISMISSED: $savePromptDismissed"|Out-File $report -Append
"ANALYZE_REISSUE_COUNT: $reissueCount"|Out-File $report -Append
if(-not$analysisReady){Shot "$prefix-analysis-timeout";throw "Analyze Position export did not become ready within ${analysisElapsed}s"}
"ANALYSIS_READY_SECONDS: $analysisElapsed"|Out-File $report -Append
Set-Content (Join-Path $env:GITHUB_WORKSPACE "$prefix-baseline.txt") $baselineText -Encoding UTF8
$baseline|ConvertTo-Json -Depth 12|Set-Content (Join-Path $env:GITHUB_WORKSPACE "$prefix-baseline.json") -Encoding UTF8
'@
if(-not$src.Contains($old)){throw 'v18 fixed Analyze Position block not found'}
$generated=$src.Replace($old,$new)

# XG can flip equal-equity rows between independent runners. Matrix rank therefore
# cannot identify a move reliably when the baseline contains a tie. Canonicalize the
# five candidates by equity descending and move text ascending, then click the row
# where that canonical move appears in this runner's actual UI ordering.
$targetOld=@'
$target=$baseline.candidates|Where-Object{$_.rank-eq$rank}|Select-Object -First 1
if($null-eq$target){throw "baseline missing rank $rank"}
$targetMove=[string]$target.move
$baselineMethod=[string]$target.analysis_method
"TARGET_MOVE: $targetMove"|Out-File $report -Append
"BASELINE_SOURCE: $($target.source)"|Out-File $report -Append
"BASELINE_METHOD: $baselineMethod"|Out-File $report -Append
"BASELINE_EQUITY: $($target.equity)"|Out-File $report -Append
Post "$prefix/target" 'success' "candidate rank $rank identified"
'@
$targetNew=@'
$canonicalCandidates=@($baseline.candidates|Sort-Object -Property @{Expression={[double]$_.equity};Descending=$true},@{Expression={[string]$_.move};Ascending=$true})
if($canonicalCandidates.Count-ne5){throw "baseline candidate count must be 5, got $($canonicalCandidates.Count)"}
if(@($canonicalCandidates|ForEach-Object{$_.move}|Select-Object -Unique).Count-ne5){throw 'baseline contains duplicate moves'}
$target=$canonicalCandidates[$rank-1]
if($null-eq$target){throw "baseline missing canonical rank $rank"}
$targetUiRank=[int]$target.rank
$targetMove=[string]$target.move
$baselineMethod=[string]$target.analysis_method
"TARGET_MOVE: $targetMove"|Out-File $report -Append
"TARGET_CANONICAL_RANK: $rank"|Out-File $report -Append
"TARGET_UI_RANK: $targetUiRank"|Out-File $report -Append
"BASELINE_SOURCE: $($target.source)"|Out-File $report -Append
"BASELINE_METHOD: $baselineMethod"|Out-File $report -Append
"BASELINE_EQUITY: $($target.equity)"|Out-File $report -Append
Post "$prefix/target" 'success' "canonical rank $rank mapped to UI rank $targetUiRank"
'@
if(-not$generated.Contains($targetOld)){throw 'v18 target selection block not found'}
$generated=$generated.Replace($targetOld,$targetNew)

$rowOld='$rowX=[int]$wr.Left+130;$rowY=[int]$wr.Top+370+(43*($rank-1))'
$rowNew='$rowX=[int]$wr.Left+130;$rowY=[int]$wr.Top+370+(43*($targetUiRank-1))'
if(-not$generated.Contains($rowOld)){throw 'v18 target row geometry block not found'}
$generated=$generated.Replace($rowOld,$rowNew)

$pollOld=@'
  try{
    $text=ExportText $xg
    if($text.Length-lt100){continue}
    $parsed=ParseExport $text "$prefix-poll"
    $hit=$parsed.candidates|Where-Object{$_.move-eq$targetMove -and $_.analysis_method-eq'XG Roller++'}|Select-Object -First 1
    if($null-ne$hit){$complete=$true;$finalText=$text;$finalParsed=$parsed;break}
    "T=${elapsed}s TARGET_METHOD_PENDING"|Out-File $report -Append
  }catch{"T=${elapsed}s PARSE_PENDING=$($_.Exception.Message)"|Out-File $report -Append}
'@
$pollNew=@'
  try{
    # XG omits the currently selected move from Ctrl+C while a row-level
    # analysis result is active. Cycle the selected row between polls so even
    # if XGR++ reorders the target, a later export necessarily selects another row.
    $probeRank=1+(($rank+[int]($elapsed/10))%5)
    $probeY=[int]$wr.Top+370+(43*($probeRank-1))
    LeftClick $rowX $probeY
    Start-Sleep -Milliseconds 250
    $text=ExportText $xg
    if($text.Length-lt100){continue}
    $partialTxt=Join-Path $env:GITHUB_WORKSPACE "$prefix-poll.txt"
    $partialJson=Join-Path $env:GITHUB_WORKSPACE "$prefix-poll.json"
    Set-Content $partialTxt $text -Encoding UTF8
    & python "$env:GITHUB_WORKSPACE\scripts\parse_xg_position_export.py" $partialTxt $partialJson --allow-partial|Out-Null
    if($LASTEXITCODE-ne0){throw "partial parse failed for $prefix-poll"}
    $parsed=Get-Content $partialJson -Raw|ConvertFrom-Json
    $hit=$parsed.candidates|Where-Object{$_.move-eq$targetMove -and $_.analysis_method-eq'XG Roller++'}|Select-Object -First 1
    if($null-ne$hit){$complete=$true;$finalText=$text;$finalParsed=$parsed;break}
    "T=${elapsed}s TARGET_METHOD_PENDING ranks=$([string]::Join(',',@($parsed.candidate_ranks)))"|Out-File $report -Append
  }catch{"T=${elapsed}s PARSE_PENDING=$($_.Exception.Message)"|Out-File $report -Append}
'@
if(-not$generated.Contains($pollOld)){throw 'v18 XGR++ polling block not found'}
$generated=$generated.Replace($pollOld,$pollNew)
$tmp=Join-Path $env:RUNNER_TEMP "xg-v21-xgrpp-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
