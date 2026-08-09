$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class R8N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint flags, UIntPtr extra);
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
function DumpMenus([string]$name){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $lines=New-Object 'System.Collections.Generic.List[string]'
  foreach($e in $all){
    try{
      $r=$e.Current.BoundingRectangle
      if($e.Current.ProcessId-eq$script:xg.Id -or $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Menu -or $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem){
        $lines.Add("PID=[$($e.Current.ProcessId)] Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
      }
    }catch{}
  }
  $lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8
}
function LeftClick([int]$x,[int]$y){
  [R8N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100
  [R8N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R8N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function RightClick([int]$x,[int]$y){
  [R8N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100
  [R8N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R8N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
}

$report="$env:GITHUB_WORKSPACE\xg-top5-v8-report.txt"
'XG Top5 Rollout v8 Submenu Probe'|Out-File $report
$script:xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$script:xg.Refresh()
if($script:xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
Post 'xg-top5-v8/xgid' 'success' 'Known XGID ready'
$hwnd=[IntPtr]$script:xg.MainWindowHandle
$main=[R8N]::GetMenu($hwnd);$analyze=[R8N]::GetSubMenu($main,4);$positionId=[R8N]::GetMenuItemID($analyze,1)
if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position command unavailable'}
[R8N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
[void][R8N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Post 'xg-top5-v8/position-command' 'success' "Analyze Position id=$positionId sent"
Start-Sleep 15

$wr=New-Object R8N+RECT
if(-not[R8N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$x=[int]$wr.Left+130
$ys=@(([int]$wr.Top+370),([int]$wr.Top+413),([int]$wr.Top+456),([int]$wr.Top+499),([int]$wr.Top+542))
LeftClick $x $ys[0]
[R8N]::keybd_event(0x11,0,0,[UIntPtr]::Zero)
try{for($i=1;$i-lt5;$i++){LeftClick $x $ys[$i];Start-Sleep -Milliseconds 100}}finally{[R8N]::keybd_event(0x11,0,2,[UIntPtr]::Zero)}
Start-Sleep -Milliseconds 500
Shot 'xg-top5-v8-selected-five'
RightClick $x $ys[4]
Start-Sleep -Milliseconds 700

$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$context=$null
foreach($m in $all){
  try{
    if($m.Current.ProcessId-eq$script:xg.Id -and $m.Current.ControlType-eq[System.Windows.Automation.ControlType]::Menu -and $m.Current.ClassName-eq'#32768'){$context=$m;break}
  }catch{}
}
if($null-eq$context){Shot 'xg-top5-v8-no-context-menu';DumpMenus 'xg-top5-v8-no-context-menu';throw 'Context menu not found'}
$children=$context.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$menuItems=@()
foreach($child in $children){try{if($child.Current.ControlType-eq[System.Windows.Automation.ControlType]::MenuItem){$menuItems+=,$child}}catch{}}
$ordered=@($menuItems|Sort-Object{try{$_.Current.BoundingRectangle.Y}catch{99999}})
"CONTEXT_MENU_ITEM_COUNT: $($ordered.Count)"|Out-File $report -Append
if($ordered.Count-lt12){Shot 'xg-top5-v8-too-few-context-items';DumpMenus 'xg-top5-v8-too-few-context-items';throw "Expected at least 12 context items, got $($ordered.Count)"}
$rolloutItem=$ordered[11]
$rr=$rolloutItem.Current.BoundingRectangle
"ROLLOUT_CONTEXT_RECT: $($rr.X),$($rr.Y),$($rr.Width),$($rr.Height)"|Out-File $report -Append
[R8N]::SetCursorPos([int]($rr.X+$rr.Width/2),[int]($rr.Y+$rr.Height/2))|Out-Null
Start-Sleep 1
Shot 'xg-top5-v8-rollout-submenu'
DumpMenus 'xg-top5-v8-rollout-submenu'
'ROLLOUT_SUBMENU_CAPTURED: True'|Out-File $report -Append
Post 'xg-top5-v8/submenu' 'success' 'Rollout submenu hovered and captured'
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
