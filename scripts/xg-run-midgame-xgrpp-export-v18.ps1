$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-run-midgame-xgrpp-export-v15.ps1'
$src=Get-Content $srcPath -Raw

$oldDialog=@'
function FindSaveGameAutomationDialog(){
  try{
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Save Game')
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Children,$nameCond)
  }catch{return $null}
}
function InvokeAutomationNo([System.Windows.Automation.AutomationElement]$dialog){
  if($null-eq$dialog){return $false}
  try{
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')
    $button=$dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$nameCond)
    if($null-eq$button){return $false}
    $pattern=$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if($null-eq$pattern){return $false}
    $pattern.Invoke()
    return $true
  }catch{return $false}
}
'@

$newDialog=@'
function FindSaveGameAutomationDialog(){
  try{
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Save Game')
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$nameCond)
    foreach($candidate in $all){
      try{
        if([string]$candidate.Current.Name -eq 'Save Game' -and $candidate.Current.IsEnabled){return $candidate}
      }catch{}
    }
  }catch{}
  return $null
}
function InvokeAutomationNo([System.Windows.Automation.AutomationElement]$dialog){
  if($null-eq$dialog){return $false}
  try{
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')
    $buttons=$dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants,$nameCond)
    foreach($button in $buttons){
      try{
        if([string]$button.Current.Name -ne 'No' -or -not$button.Current.IsEnabled){continue}
        try{
          $pattern=$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          if($null-ne$pattern){$pattern.Invoke();return $true}
        }catch{}
        $r=$button.Current.BoundingRectangle
        if($r.Width-gt0 -and $r.Height-gt0){
          LeftClick ([int]($r.X+$r.Width/2)) ([int]($r.Y+$r.Height/2))
          return $true
        }
      }catch{}
    }
  }catch{}
  return $false
}
'@

if(-not$src.Contains($oldDialog)){throw 'v15 Save Game automation block not found'}
$src=$src.Replace($oldDialog,$newDialog)

$oldBaseline=@'
$baseline=ExportText
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
$beforeSource=TopSource $baseline
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source'}
'@

$newBaseline=@'
$baseline=''
$beforeSource=''
for($baselineAttempt=1;$baselineAttempt-le3 -and -not$beforeSource;$baselineAttempt++){
  $baseline=ExportText
  $beforeSource=TopSource $baseline
  $looksLikeXgid=$baseline.Trim().StartsWith('XGID=')
  "BASELINE_ATTEMPT_${baselineAttempt}_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_SOURCE: $beforeSource"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_XGID_ONLY: $looksLikeXgid"|Out-File $report15 -Append
  if($beforeSource){break}
  if($looksLikeXgid -or $baseline.Length-lt100){
    $retryDismissed=DismissDelayedSaveGame
    "BASELINE_ATTEMPT_${baselineAttempt}_SAVE_DISMISSED: $retryDismissed"|Out-File $report15 -Append
    if($retryDismissed){Post 'xg-public-v18/save-dialog-dismissed' 'success' "Save Game dismissed on baseline attempt $baselineAttempt"}
    InvokeAnalyzePosition
    Post 'xg-public-v18/midgame-analyze-retry' 'success' "baseline attempt $baselineAttempt reissued Analyze Position"
    Start-Sleep 20
    Shot "$env:GITHUB_WORKSPACE\xg-v18-baseline-retry-${baselineAttempt}.png"
  }
}
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source after v18 dialog recovery'}
'@

if(-not$src.Contains($oldBaseline)){throw 'v15 baseline block not found'}
$src=$src.Replace($oldBaseline,$newBaseline)

$oldCommand=@'
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
'@

$newCommand=@'
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class V18M {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string className, string windowName);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetMenuString(IntPtr hMenu, uint uIDItem, StringBuilder lpString, int cchMax, uint flags);
  [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuState(IntPtr hMenu, uint uId, uint flags);
}
"@
$wr=New-Object V15N+RECT
if(-not[V15N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$bestX=$wr.Left+130;$bestY=$wr.Top+364
[V15N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
RightClick $bestX $bestY
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v18-context-before-xgrpp.png"
$popup=[IntPtr]::Zero
for($popupTry=0;$popupTry-lt20 -and $popup-eq[IntPtr]::Zero;$popupTry++){
  $popup=[V18M]::FindWindow('#32768',$null)
  if($popup-eq[IntPtr]::Zero){Start-Sleep -Milliseconds 100}
}
if($popup-eq[IntPtr]::Zero){throw 'Standard popup menu window #32768 not found'}
$MN_GETHMENU=0x01E1
$hmenu=[V18M]::SendMessage($popup,$MN_GETHMENU,[IntPtr]::Zero,[IntPtr]::Zero)
if($hmenu-eq[IntPtr]::Zero){throw 'MN_GETHMENU returned zero'}
$count=[V18M]::GetMenuItemCount($hmenu)
if($count-le0){throw "Context HMENU had invalid item count $count"}
$menuDump="$env:GITHUB_WORKSPACE\xg-v18-context-menu.txt"
"POPUP_HWND: $popup"|Out-File $menuDump
"HMENU: $hmenu"|Out-File $menuDump -Append
"ITEM_COUNT: $count"|Out-File $menuDump -Append
$targetId=[uint32]::MaxValue
$targetPos=-1
for($i=0;$i-lt$count;$i++){
  $sb=New-Object System.Text.StringBuilder 512
  [void][V18M]::GetMenuString($hmenu,[uint32]$i,$sb,$sb.Capacity,0x400)
  $txt=$sb.ToString()
  $id=[V18M]::GetMenuItemID($hmenu,$i)
  $state=[V18M]::GetMenuState($hmenu,[uint32]$i,0x400)
  "POS=$i ID=$id STATE=0x$('{0:X}' -f $state) TEXT=[$txt]"|Out-File $menuDump -Append
  $norm=($txt -replace '&','').Split("`t")[0].Trim()
  if($norm-eq'XG Roller++'){$targetId=$id;$targetPos=$i}
}
if($targetPos-lt0 -or $targetId-eq[uint32]::MaxValue){throw 'Could not resolve XG Roller++ command id from live context HMENU'}
$targetState=[V18M]::GetMenuState($hmenu,[uint32]$targetPos,0x400)
if(($targetState-band0x3)-ne0){throw "XG Roller++ menu item disabled state=0x$('{0:X}' -f $targetState)"}
"XGRPP_COMMAND_ID: $targetId"|Out-File $report15 -Append
"XGRPP_COMMAND_POSITION: $targetPos"|Out-File $report15 -Append
"XGRPP_COMMAND_STATE: 0x$('{0:X}' -f $targetState)"|Out-File $report15 -Append
Post 'xg-public-v18/xgrpp-command-resolved' 'success' "XG Roller++ id=$targetId pos=$targetPos"
$cpuBefore=$xg.TotalProcessorTime.TotalSeconds
[void][V18M]::SendMessage($hwnd,0x0111,[IntPtr]([uint32]$targetId),[IntPtr]::Zero)
'XGRPP_COMMAND_INVOKED_BY_ID: True'|Out-File $report15 -Append
'ROLLOUT_MENU_COMMAND_CLICKED: False'|Out-File $report15 -Append
Start-Sleep 2
$xg.Refresh()
$cpuAfter=$xg.TotalProcessorTime.TotalSeconds
"XGRPP_CPU_SECONDS_BEFORE: $cpuBefore"|Out-File $report15 -Append
"XGRPP_CPU_SECONDS_AFTER_2S: $cpuAfter"|Out-File $report15 -Append
Shot "$env:GITHUB_WORKSPACE\xg-v18-after-command.png"
Post 'xg-public-v18/xgrpp-started' 'success' 'XG Roller++ invoked by live menu command id'
'@

if(-not$src.Contains($oldCommand)){throw 'v15 XG Roller++ coordinate command block not found'}
$src=$src.Replace($oldCommand,$newCommand)
$src=$src.Replace("if($sourceNow-eq'XG Roller++'){$complete=$true}","if($sourceNow-like'XG Roller++*'){$complete=$true}")
$src=$src.Replace('xg-v15-xgrpp-${elapsed}s.png','xg-v18-xgrpp-${elapsed}s.png')
$src=$src.Replace("Post 'xg-public-v15/xgrpp-export-confirmed'","Post 'xg-public-v18/xgrpp-export-confirmed'")
$tmp=Join-Path $env:RUNNER_TEMP 'xg-v18-patched.ps1'
Set-Content $tmp $src -Encoding UTF8
& $tmp
