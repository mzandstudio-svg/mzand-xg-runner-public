$ErrorActionPreference='Stop'
. ./scripts/xg-launch-top5-rollout-core-v18.ps1

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class RollProgN {
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
"@

$report="$env:GITHUB_WORKSPACE\xg-top5-v19-completion.txt"
'XG Top5 Rollout v19 Completion Watch'|Out-File $report
$PBM_GETRANGE=0x0407
$PBM_GETPOS=0x0408

function GetBars {
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $bars=@()
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-eq$script:xg.Id -and $e.Current.ClassName-eq'TProgressBar'){
        $h=[IntPtr]$e.Current.NativeWindowHandle
        if($h-ne[IntPtr]::Zero){$bars+=,$h}
      }
    }catch{}
  }
  return @($bars|Sort-Object {[int64]$_} -Unique)
}
function ReadBar([IntPtr]$h){
  $pos=[int][RollProgN]::SendMessage($h,$PBM_GETPOS,[IntPtr]::Zero,[IntPtr]::Zero)
  $low=[int][RollProgN]::SendMessage($h,$PBM_GETRANGE,[IntPtr]1,[IntPtr]::Zero)
  $high=[int][RollProgN]::SendMessage($h,$PBM_GETRANGE,[IntPtr]::Zero,[IntPtr]::Zero)
  return [pscustomobject]@{Handle=$h;Pos=$pos;Low=$low;High=$high}
}
function DumpFinalUI([string]$name){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $lines=New-Object 'System.Collections.Generic.List[string]'
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-eq$script:xg.Id){
        $r=$e.Current.BoundingRectangle
        $lines.Add("Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Handle=[$($e.Current.NativeWindowHandle)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
      }
    }catch{}
  }
  $lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8
}

Start-Sleep 3
$bars=GetBars
if($bars.Count-lt1){Shot 'xg-top5-v19-no-progress-bars';throw 'No TProgressBar found after rollout launch'}
$initial=@($bars|ForEach-Object{ReadBar $_})
foreach($b in $initial){"INITIAL Handle=$($b.Handle) Range=$($b.Low)..$($b.High) Pos=$($b.Pos)"|Out-File $report -Append}
$valid=@($initial|Where-Object{$_.High-gt0})
if($valid.Count-lt1){throw 'No progress bar with positive range'}
$target=($valid|Measure-Object High -Maximum).Maximum
"TARGET_HIGH: $target"|Out-File $report -Append
Post 'xg-top5-v19/range-read' 'success' "Native rollout progress target=$target"

$maxSeen=0
$everActive=$false
$complete=$false
$pollSeconds=30
$maxPolls=150
for($poll=1;$poll-le$maxPolls;$poll++){
  if($script:xg.HasExited){throw 'XG exited during rollout'}
  $bars=GetBars
  $states=@()
  foreach($h in $bars){$states+=,(ReadBar $h)}
  $positions=@($states|Where-Object{$_.High-gt0}|ForEach-Object{$_.Pos})
  if($positions.Count-gt0){$pos=($positions|Measure-Object -Maximum).Maximum}else{$pos=0}
  if($pos-gt$maxSeen){$maxSeen=$pos}
  if($pos-gt0){$everActive=$true}
  $pct=if($target-gt0){[math]::Round(100.0*$pos/$target,2)}else{0}
  $elapsed=$poll*$pollSeconds
  "POLL=$poll ELAPSED_S=$elapsed POS=$pos MAX_SEEN=$maxSeen TARGET=$target PCT=$pct BARS=$($bars.Count)"|Out-File $report -Append

  if($poll-eq1 -or $poll%10-eq0){
    Shot "xg-top5-v19-progress-$elapsed`s"
    Post "xg-top5-v19/progress-$elapsed`s" 'success' "rollout progress $pct% ($pos/$target)"
  }

  # Direct completion at the native high-water mark.
  if($target-gt0 -and $pos-ge($target-1)){$complete=$true;break}
  # XG may reset progress to zero immediately after completion; only trust that
  # after at least 95% of the native range has already been observed.
  if($everActive -and $target-gt0 -and $maxSeen-ge[math]::Floor(0.95*$target) -and $pos-eq0){$complete=$true;break}

  Start-Sleep -Seconds $pollSeconds
}

if(-not$complete){
  Shot 'xg-top5-v19-timeout'
  DumpFinalUI 'xg-top5-v19-timeout'
  throw "Rollout did not reach completion signal; max=$maxSeen target=$target"
}

"COMPLETION_SIGNAL: True"|Out-File $report -Append
"FINAL_MAX_SEEN: $maxSeen"|Out-File $report -Append
"FINAL_TARGET: $target"|Out-File $report -Append
Post 'xg-top5-v19/completion-signal' 'success' "Rollout completion signal reached; max=$maxSeen target=$target"
Start-Sleep 5
Shot 'xg-top5-v19-complete'
DumpFinalUI 'xg-top5-v19-complete'
$script:xg.Refresh()
"XG_RESPONDING_FINAL: $($script:xg.Responding)"|Out-File $report -Append
Get-Content $report
Post 'xg-top5-v19/final-captured' 'success' 'Captured completed rollout position'
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
