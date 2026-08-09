$ErrorActionPreference='Stop'

$yaml=Get-Content "$env:GITHUB_WORKSPACE\.github\workflows\xg-analyze-level-public-v1.yml" -Raw
$m=[regex]::Match($yaml,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not$m.Success){throw 'Could not extract public v1 proven startup'}
$script=$m.Groups['script'].Value -replace '(?m)^          ',''
$script=$script.Replace('xg-public-v1-report.txt','xg-public-v3-report.txt').Replace('XG public Analyze Level v1','XG public Analyze Level v3')

$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$script.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v1 XGID_POSITION_READY marker missing'}
$prefix=$script.Substring(0,$idx+$marker.Length)

$frontier=@'

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class MenuN {
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetMenuString(IntPtr hMenu, uint uIDItem, StringBuilder lpString, int nMaxCount, uint uFlag);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
"@

function MenuText([IntPtr]$h,[int]$pos){
  $sb=New-Object System.Text.StringBuilder 512
  [void][MenuN]::GetMenuString($h,[uint32]$pos,$sb,$sb.Capacity,0x400)
  return [string]$sb.ToString()
}
function NormalizeMenu([string]$s){
  if($null-eq$s){return ''}
  return (($s -replace '&','') -split "`t")[0].Trim()
}
function Post-Here([string]$context,[string]$state,[string]$description){
  try{
    $payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress
    $headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'}
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null
  }catch{}
}

$xg.Refresh()
$hwnd=[IntPtr]$xg.MainWindowHandle
$mainMenu=[MenuN]::GetMenu($hwnd)
"WIN32_MAIN_MENU_HANDLE: $mainMenu"|Out-File $report -Append
if($mainMenu-eq[IntPtr]::Zero){Snap 'win32-main-menu-zero';throw 'GetMenu returned zero'}

$topCount=[MenuN]::GetMenuItemCount($mainMenu)
"WIN32_TOP_MENU_COUNT: $topCount"|Out-File $report -Append
Post-Here "xg-public-v3/top-count-$topCount" 'success' "top-level menu count=$topCount"
$topDump=New-Object 'System.Collections.Generic.List[string]'
$analyzeIndex=-1
for($i=0;$i-lt$topCount;$i++){
  $raw=MenuText $mainMenu $i
  $norm=NormalizeMenu $raw
  $sub=[MenuN]::GetSubMenu($mainMenu,$i)
  $topDump.Add("Index=[$i] Raw=[$raw] Normalized=[$norm] SubMenu=[$sub]")
  $safe=($norm -replace '[^A-Za-z0-9_-]','-').Trim('-')
  if($safe){Post-Here "xg-public-v3/top-$i-$safe" 'success' "top menu $i=$norm"}
  if($norm-eq'Analyze'){$analyzeIndex=$i}
}
$topDump|Out-File "$env:GITHUB_WORKSPACE\xg-win32-top-menu.txt" -Encoding utf8
"WIN32_ANALYZE_INDEX: $analyzeIndex"|Out-File $report -Append
if($analyzeIndex-lt0){Snap 'win32-analyze-not-found';throw 'Analyze top-level menu not found by Win32'}

$analyzeMenu=[MenuN]::GetSubMenu($mainMenu,$analyzeIndex)
if($analyzeMenu-eq[IntPtr]::Zero){throw 'Analyze submenu handle is zero'}
$count=[MenuN]::GetMenuItemCount($analyzeMenu)
"WIN32_ANALYZE_ITEM_COUNT: $count"|Out-File $report -Append
Post-Here "xg-public-v3/analyze-count-$count" 'success' "Analyze item count=$count"
$dump=New-Object 'System.Collections.Generic.List[string]'
$setIndex=-1
$setId=[uint32]0xFFFFFFFF
$setChild=[IntPtr]::Zero
for($i=0;$i-lt$count;$i++){
  $raw=MenuText $analyzeMenu $i
  $norm=NormalizeMenu $raw
  $id=[MenuN]::GetMenuItemID($analyzeMenu,$i)
  $child=[MenuN]::GetSubMenu($analyzeMenu,$i)
  $dump.Add("Index=[$i] Raw=[$raw] Normalized=[$norm] CommandId=[$id] Child=[$child]")
  $safe=($norm -replace '[^A-Za-z0-9_-]','-').Trim('-')
  if($safe){Post-Here "xg-public-v3/analyze-$i-$safe" 'success' "Analyze menu item $i=$norm"}
  if($norm-eq'Set Analyze Level'){$setIndex=$i;$setId=$id;$setChild=$child}
}
$dump|Out-File "$env:GITHUB_WORKSPACE\xg-win32-analyze-menu.txt" -Encoding utf8
"WIN32_SET_ANALYZE_LEVEL_INDEX: $setIndex"|Out-File $report -Append
"WIN32_SET_ANALYZE_LEVEL_ID: $setId"|Out-File $report -Append
"WIN32_SET_ANALYZE_LEVEL_CHILD: $setChild"|Out-File $report -Append
if($setIndex-lt0){Snap 'win32-set-analyze-not-found';throw 'Set Analyze Level not found by exact Win32 menu text'}
if($setChild-ne[IntPtr]::Zero){Snap 'win32-set-analyze-is-submenu';throw 'Set Analyze Level is a submenu; not invoking blindly'}
if($setId-eq[uint32]0xFFFFFFFF){throw 'Set Analyze Level has no command id'}
Post-Here "xg-public-v3/set-level-id-$setId" 'success' "exact Set Analyze Level command id=$setId"

[N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
[void][MenuN]::SendMessage($hwnd,0x0111,[IntPtr]([int]$setId),[IntPtr]::Zero)
'SET_ANALYZE_LEVEL_COMMAND_SENT: True'|Out-File $report -Append
Start-Sleep 2
Snap 'set-analyze-level-dialog-win32'

$tops=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$topDump2=New-Object 'System.Collections.Generic.List[string]'
$dialogCandidates=0
foreach($tw in $tops){
  try{
    if($tw.Current.ProcessId-eq$xg.Id){
      $r=$tw.Current.BoundingRectangle
      $topDump2.Add("Name=[$($tw.Current.Name)] Class=[$($tw.Current.ClassName)] Handle=[$($tw.Current.NativeWindowHandle)] Enabled=[$($tw.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
      if(([IntPtr]$tw.Current.NativeWindowHandle)-ne$hwnd){$dialogCandidates++}
    }
  }catch{}
}
$topDump2|Out-File "$env:GITHUB_WORKSPACE\xg-win32-set-level-top-windows.txt" -Encoding utf8
"SET_ANALYZE_LEVEL_DIALOG_CANDIDATES: $dialogCandidates"|Out-File $report -Append
$dialogState=if($dialogCandidates-gt0){'success'}else{'failure'}
Post-Here "xg-public-v3/dialog-candidates-$dialogCandidates" $dialogState "dialog candidates=$dialogCandidates"
$xg.Refresh()
"XG_RESPONDING_FINAL: $($xg.Responding)"|Out-File $report -Append
'ANALYZE_FRONTIER_CAPTURED: True'|Out-File $report -Append
Get-Content $report
Get-Process|Where-Object{$_.ProcessName-match'^eXtremeGammon2$|^test3d$'}|Stop-Process -Force -ErrorAction SilentlyContinue
'@

$ps1=Join-Path $env:RUNNER_TEMP 'xg-public-v3-generated.ps1'
Set-Content $ps1 ($prefix+$frontier) -Encoding UTF8
& $ps1
