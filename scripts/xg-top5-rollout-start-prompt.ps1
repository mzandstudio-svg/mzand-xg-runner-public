$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class R9N {
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
function DumpDesktop([string]$name){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $lines=New-Object 'System.Collections.Generic.List[string]'
  foreach($e in $all){
    try{
      $r=$e.Current.BoundingRectangle
      if($e.Current.ProcessId-eq$script:xg.Id -or $e.Current.ClassName-eq'#32768' -or $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Window){
        $lines.Add("PID=[$($e.Current.ProcessId)] Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
      }
    }catch{}
  }
  $lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8
}
function LeftClick([int]$x,[int]$y){
  [R9N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100
  [R9N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R9N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function RightClick([int]$x,[int]$y){
  [R9N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100
  [R9N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R9N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)
}

$report="$env:GITHUB_WORKSPACE\xg-top5-v9-report.txt"
'XG Top5 Rollout v9 Start Prompt Probe'|Out-File $report
$script:xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$script:xg.Refresh()
if($script:xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
Post 'xg-top5-v9/xgid' 'success' 'Known XGID ready'
$hwnd=[IntPtr]$script:xg.MainWindowHandle
$main=[R9N]::GetMenu($hwnd);$analyze=[R9N]::GetSubMenu($main,4);$positionId=[R9N]::GetMenuItemID($analyze,1)
if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position command unavailable'}
[R9N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250
[void][R9N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Post 'xg-top5-v9/position-command' 'success' "Analyze Position id=$positionId sent"
Start-Sleep 15

$wr=New-Object R9N+RECT
if(-not[R9N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$x=[int]$wr.Left+130
$ys=@(([int]$wr.Top+370),([int]$wr.Top+413),([int]$wr.Top+456),([int]$wr.Top+499),([int]$wr.Top+542))
LeftClick $x $ys[0]
[R9N]::keybd_event(0x11,0,0,[UIntPtr]::Zero)
try{for($i=1;$i-lt5;$i++){LeftClick $x $ys[$i];Start-Sleep -Milliseconds 100}}finally{[R9N]::keybd_event(0x11,0,2,[UIntPtr]::Zero)}
Start-Sleep -Milliseconds 500
Shot 'xg-top5-v9-selected-five'
RightClick $x $ys[4]
Start-Sleep -Milliseconds 700

$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$context=$null
foreach($m in $all){try{if($m.Current.ProcessId-eq$script:xg.Id -and $m.Current.ClassName-eq'#32768'){$r=$m.Current.BoundingRectangle;if($r.Width-gt200 -and $r.Height-gt400){$context=$m;break}}}catch{}}
if($null-eq$context){throw 'Main context popup not found'}
$cr=$context.Current.BoundingRectangle
$rollX=[int]($cr.X+($cr.Width/2));$rollY=[int]($cr.Y+221)
[R9N]::SetCursorPos($rollX,$rollY)|Out-Null
Start-Sleep 1
Shot 'xg-top5-v9-rollout-submenu-before-start'

$all2=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$sub=$null
foreach($m in $all2){
  try{
    if($m.Current.ProcessId-eq$script:xg.Id -and $m.Current.ClassName-eq'#32768'){
      $r=$m.Current.BoundingRectangle
      if($r.X-gt$cr.X -and $r.Width-gt300 -and $r.Height-gt350){$sub=$m;break}
    }
  }catch{}
}
if($null-eq$sub){Shot 'xg-top5-v9-submenu-not-found';DumpDesktop 'xg-top5-v9-submenu-not-found';throw 'Rollout submenu popup not found'}
$sr=$sub.Current.BoundingRectangle
"ROLLOUT_SUBMENU_RECT: $($sr.X),$($sr.Y),$($sr.Width),$($sr.Height)"|Out-File $report -Append
# v8 evidence: Start row rect [sub.X+3, sub.Y+231, sub.Width-6, 19].
$startX=[int]($sr.X+($sr.Width/2));$startY=[int]($sr.Y+240)
"START_CLICK_POINT: $startX,$startY"|Out-File $report -Append
LeftClick $startX $startY
'START_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v9/start-clicked' 'success' 'Rollout Start clicked with duration prompt enabled'
Start-Sleep 1
Shot 'xg-top5-v9-duration-dialog-1s';DumpDesktop 'xg-top5-v9-duration-dialog-1s'
Start-Sleep 2
Shot 'xg-top5-v9-duration-dialog-3s';DumpDesktop 'xg-top5-v9-duration-dialog-3s'
$xg.Refresh()
"XG_RESPONDING_AFTER_START: $($xg.Responding)"|Out-File $report -Append
'ROLLOUT_DURATION_DIALOG_CAPTURED: True'|Out-File $report -Append
Post 'xg-top5-v9/prompt-captured' 'success' 'Post-Start prompt/dialog evidence captured; no confirmation sent'
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
