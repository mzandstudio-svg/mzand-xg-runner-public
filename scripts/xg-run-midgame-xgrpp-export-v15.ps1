$ErrorActionPreference='Stop'
$src=Get-Content "$env:GITHUB_WORKSPACE\scripts\xg-run-position-analysis-v8.ps1" -Raw
$marker='Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue'
$idx=$src.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v8 cleanup marker missing'}
$prefix=$src.Substring(0,$idx)
$tail=@'

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V15N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function LeftClick([int]$x,[int]$y){[V15N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V15N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V15N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function RightClick([int]$x,[int]$y){[V15N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V15N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V15N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)}
function ExportText(){
  $xg.Refresh()
  [V15N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^c')
  Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
function TopSource([string]$text){
  $m=[regex]::Match($text,'(?m)^\s*1\.\s+(.+?)\s{2,}\S.*?\s+eq:[+-]\d+\.\d+')
  if($m.Success){return $m.Groups[1].Value.Trim()}
  return ''
}
function InvokeAnalyzePosition(){
  $xg.Refresh()
  $hwnd=[IntPtr]$xg.MainWindowHandle
  $menu=[V8N]::GetMenu($hwnd)
  $top=New-Object V8N+RECT
  if(-not[V8N]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed after midgame switch'}
  [V8N]::SetForegroundWindow($hwnd)|Out-Null
  Start-Sleep -Milliseconds 250
  ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2))
  Start-Sleep -Milliseconds 500
  $sub=[V8N]::GetSubMenu($menu,4)
  $pos=New-Object V8N+RECT
  if(-not[V8N]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)){throw 'Analyze Position row rect failed after midgame switch'}
  ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
}
function DismissDelayedSaveGame(){
  Start-Sleep 2
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($w in $all){
    try{
      if($w.Current.ProcessId-eq$xg.Id -and $w.Current.Name-eq'Save Game'){
        $buttons=$w.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
        foreach($b in $buttons){
          if($b.Current.Name-eq'No' -and $b.Current.ControlType-eq[System.Windows.Automation.ControlType]::Button){
            $p=$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            ([System.Windows.Automation.InvokePattern]$p).Invoke()
            Start-Sleep 1
            return $true
          }
        }
      }
    }catch{}
  }
  return $false
}

& "$env:GITHUB_WORKSPACE\scripts\xg-switch-midgame-v15.ps1"
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
InvokeAnalyzePosition
Post 'xg-public-v15/midgame-analyze-started' 'success' 'Analyze Position clicked for non-book midgame control'
$saveDismissed=DismissDelayedSaveGame
if($saveDismissed){
  Post 'xg-public-v15/delayed-save-dismissed' 'success' 'Delayed Save Game prompt dismissed with No'
  InvokeAnalyzePosition
  Post 'xg-public-v15/midgame-analyze-reissued' 'success' 'Analyze Position reissued after delayed Save Game prompt'
}
Start-Sleep 20
Shot "$env:GITHUB_WORKSPACE\xg-v15-midgame-analysis.png"

$xg.Refresh()
$hwnd=[IntPtr]$xg.MainWindowHandle
$report15="$env:GITHUB_WORKSPACE\xg-v15-xgrpp-report.txt"
"DELAYED_SAVE_GAME_DISMISSED: $saveDismissed"|Out-File $report15
$baseline=ExportText
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
$beforeSource=TopSource $baseline
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source'}
if($beforeSource-like'Book*'){throw "Midgame control unexpectedly hit Book source [$beforeSource]"}
Post 'xg-public-v15/nonbook-baseline' 'success' "baseline top source=$beforeSource"

$wr=New-Object V15N+RECT
if(-not[V15N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$bestX=$wr.Left+130;$bestY=$wr.Top+364
[V15N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
RightClick $bestX $bestY
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v15-context-before-xgrpp.png"
$xgrX=$wr.Left+230;$xgrY=$wr.Top+448
"XGRPP_CLICK_POINT: $xgrX,$xgrY"|Out-File $report15 -Append
LeftClick $xgrX $xgrY
'XGRPP_COMMAND_CLICKED: True'|Out-File $report15 -Append
'ROLLOUT_MENU_COMMAND_CLICKED: False'|Out-File $report15 -Append
Post 'xg-public-v15/xgrpp-started' 'success' 'XG Roller++ clicked for non-book top candidate'

$complete=$false
$elapsed=0
$final=''
while($elapsed-lt600 -and -not$complete){
  Start-Sleep 10
  $elapsed+=10
  $xg.Refresh()
  if($xg.HasExited){throw 'XG exited during XG Roller++'}
  if($elapsed -in @(10,30,60,120,300,600)){Shot "$env:GITHUB_WORKSPACE\xg-v15-xgrpp-${elapsed}s.png"}
  if($xg.Responding){
    $candidateText=ExportText
    if($candidateText.Length-gt100){
      $final=$candidateText
      $sourceNow=TopSource $candidateText
      "T=${elapsed}s SOURCE=$sourceNow"|Out-File $report15 -Append
      if($sourceNow-eq'XG Roller++'){$complete=$true}
    }else{
      "T=${elapsed}s CLIPBOARD_TOO_SHORT=$($candidateText.Length)"|Out-File $report15 -Append
    }
  }else{
    "T=${elapsed}s XG_RESPONDING=False"|Out-File $report15 -Append
  }
}
if($final.Length-gt0){Set-Content "$env:GITHUB_WORKSPACE\xg-v15-after-xgrpp.txt" $final -Encoding UTF8}
"XGRPP_COMPLETED_BY_EXPORT: $complete"|Out-File $report15 -Append
"XGRPP_ELAPSED_SECONDS: $elapsed"|Out-File $report15 -Append
if(-not$complete){throw 'XG Roller++ did not become the exported top source within 600 seconds'}
Post 'xg-public-v15/xgrpp-export-confirmed' 'success' "exported top source became XG Roller++ after ${elapsed}s"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$generated=Join-Path $env:RUNNER_TEMP 'xg-v15-generated.ps1'
Set-Content $generated ($prefix+$tail) -Encoding UTF8
& $generated
