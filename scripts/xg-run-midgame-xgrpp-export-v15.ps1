$ErrorActionPreference='Stop'
$src=Get-Content "$env:GITHUB_WORKSPACE\scripts\xg-run-position-analysis-v8.ps1" -Raw
$marker='Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue'
$idx=$src.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v8 cleanup marker missing'}
$prefix=$src.Substring(0,$idx)
$tail=@'

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V15N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string className, string windowName);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr childAfter, string className, string windowName);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
"@
function LeftClick([int]$x,[int]$y){[V15N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V15N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V15N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function RightClick([int]$x,[int]$y){[V15N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V15N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V15N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)}
function ExportText(){
  $xg.Refresh(); [V15N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null; Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait('^c'); Start-Sleep -Milliseconds 700
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
function TopSource([string]$text){
  $m=[regex]::Match($text,'(?m)^\s*1\.\s+(.+?)\s{2,}\S.*?\s+eq:[+-]\d+\.\d+')
  if($m.Success){return $m.Groups[1].Value.Trim()}; return ''
}
function InvokeAnalyzePosition(){
  $xg.Refresh(); $hwnd=[IntPtr]$xg.MainWindowHandle; $menu=[V8N]::GetMenu($hwnd); $top=New-Object V8N+RECT
  if(-not[V8N]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed after midgame switch'}
  [V8N]::SetForegroundWindow($hwnd)|Out-Null; Start-Sleep -Milliseconds 250
  ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2)); Start-Sleep -Milliseconds 500
  $sub=[V8N]::GetSubMenu($menu,4); $pos=New-Object V8N+RECT
  if(-not[V8N]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)){throw 'Analyze Position row rect failed after midgame switch'}
  ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
}
function FindSaveGameAutomationDialog(){
  try{$root=[System.Windows.Automation.AutomationElement]::RootElement;$c=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Save Game');return $root.FindFirst([System.Windows.Automation.TreeScope]::Children,$c)}catch{return $null}
}
function InvokeAutomationNo([System.Windows.Automation.AutomationElement]$dialog){
  if($null-eq$dialog){return $false}; try{$c=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No');$b=$dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$c);if($null-eq$b){return $false};$p=$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern);if($null-eq$p){return $false};$p.Invoke();return $true}catch{return $false}
}
function DismissDelayedSaveGame(){
  $deadline=(Get-Date).AddSeconds(35)
  while((Get-Date)-lt$deadline){
    $dialog=[V15N]::FindWindow($null,'Save Game')
    if($dialog-ne[IntPtr]::Zero){
      $noButton=[V15N]::FindWindowEx($dialog,[IntPtr]::Zero,'Button','No')
      if($noButton-ne[IntPtr]::Zero){[V15N]::SendMessage($noButton,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null;Start-Sleep 1;if([V15N]::FindWindow($null,'Save Game')-eq[IntPtr]::Zero -and $null-eq(FindSaveGameAutomationDialog)){return $true}}
      [V15N]::SetForegroundWindow($dialog)|Out-Null;Start-Sleep -Milliseconds 250;[System.Windows.Forms.SendKeys]::SendWait('%n');Start-Sleep 1
      if([V15N]::FindWindow($null,'Save Game')-eq[IntPtr]::Zero -and $null-eq(FindSaveGameAutomationDialog)){return $true}
    }
    $autoDialog=FindSaveGameAutomationDialog
    if($null-ne$autoDialog -and (InvokeAutomationNo $autoDialog)){Start-Sleep 1;if([V15N]::FindWindow($null,'Save Game')-eq[IntPtr]::Zero -and $null-eq(FindSaveGameAutomationDialog)){return $true}}
    Start-Sleep -Milliseconds 500
  }
  return $false
}

& "$env:GITHUB_WORKSPACE\scripts\xg-switch-midgame-v15.ps1"
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh(); InvokeAnalyzePosition
Post 'xg-public-v15/midgame-analyze-started' 'success' 'Analyze Position clicked for target position'
$saveDismissed=DismissDelayedSaveGame
if($saveDismissed){Post 'xg-public-v15/delayed-save-dismissed' 'success' 'Delayed Save Game prompt dismissed with No';InvokeAnalyzePosition;Post 'xg-public-v15/midgame-analyze-reissued' 'success' 'Analyze Position reissued'}
Start-Sleep 20
Shot "$env:GITHUB_WORKSPACE\xg-v15-midgame-analysis.png"

$xg.Refresh(); $hwnd=[IntPtr]$xg.MainWindowHandle; $report15="$env:GITHUB_WORKSPACE\xg-v15-xgrpp-report.txt"
"DELAYED_SAVE_GAME_DISMISSED: $saveDismissed"|Out-File $report15
$baseline=ExportText
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
$beforeSource=TopSource $baseline
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source'}

# GT724 corpus fast path: capture the real XG baseline for every target and stop.
# Selected divergences can be escalated to XG Roller++ in a second, bounded workflow.
if($env:MZAND_XG_BASELINE_ONLY-eq'1'){
  Set-Content "$env:GITHUB_WORKSPACE\xg-v15-after-xgrpp.txt" $baseline -Encoding UTF8
  'BASELINE_ONLY: True'|Out-File $report15 -Append
  Post 'gt724-xg-corpus/baseline-exported' 'success' "baseline source=$beforeSource"
  Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
  return
}

if($beforeSource-like'Book*'){throw "Midgame control unexpectedly hit Book source [$beforeSource]"}
Post 'xg-public-v15/nonbook-baseline' 'success' "baseline top source=$beforeSource"
$wr=New-Object V15N+RECT
if(-not[V15N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$bestX=$wr.Left+130;$bestY=$wr.Top+364
[V15N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250;RightClick $bestX $bestY;Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v15-context-before-xgrpp.png"
$xgrX=$wr.Left+230;$xgrY=$wr.Top+448
"XGRPP_CLICK_POINT: $xgrX,$xgrY"|Out-File $report15 -Append
LeftClick $xgrX $xgrY
'XGRPP_COMMAND_CLICKED: True'|Out-File $report15 -Append
'ROLLOUT_MENU_COMMAND_CLICKED: False'|Out-File $report15 -Append
Post 'xg-public-v15/xgrpp-started' 'success' 'XG Roller++ clicked for non-book top candidate'
$complete=$false;$elapsed=0;$final=''
while($elapsed-lt600 -and -not$complete){
  Start-Sleep 10;$elapsed+=10;$xg.Refresh();if($xg.HasExited){throw 'XG exited during XG Roller++'}
  if($elapsed -in @(10,30,60,120,300,600)){Shot "$env:GITHUB_WORKSPACE\xg-v15-xgrpp-${elapsed}s.png"}
  if($xg.Responding){$candidateText=ExportText;if($candidateText.Length-gt100){$final=$candidateText;$sourceNow=TopSource $candidateText;"T=${elapsed}s SOURCE=$sourceNow"|Out-File $report15 -Append;if($sourceNow-eq'XG Roller++'){$complete=$true}}else{"T=${elapsed}s CLIPBOARD_TOO_SHORT=$($candidateText.Length)"|Out-File $report15 -Append}}else{"T=${elapsed}s XG_RESPONDING=False"|Out-File $report15 -Append}
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
