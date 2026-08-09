$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class R10N {
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
function Post([string]$context,[string]$state,[string]$description){try{$payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress;$headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'};Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null}catch{}}
function Shot([string]$name){$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save("$env:GITHUB_WORKSPACE\$name.png",[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}
function DumpDesktop([string]$name){$root=[System.Windows.Automation.AutomationElement]::RootElement;$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition);$lines=New-Object 'System.Collections.Generic.List[string]';foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$script:xg.Id -or $e.Current.ClassName-eq'#32768' -or $e.Current.ControlType-eq[System.Windows.Automation.ControlType]::Window){$lines.Add("PID=[$($e.Current.ProcessId)] Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")}}catch{}};$lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8}
function LeftClick([int]$x,[int]$y){[R10N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100;[R10N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R10N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function RightClick([int]$x,[int]$y){[R10N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100;[R10N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R10N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)}
function HoverRollout([int]$rowX,[int]$row5Y){
  RightClick $rowX $row5Y
  Start-Sleep -Milliseconds 700
  # Proven v7/v8 geometry: context popup left=rowX; popup bottom=row5Y; height=424; Rollout center offset +114,+221 from popup top.
  $contextTop=$row5Y-424
  $rollX=$rowX+114
  $rollY=$contextTop+221
  [R10N]::SetCursorPos($rollX,$rollY)|Out-Null
  Start-Sleep 1
  return @($rowX+222,$contextTop+209)
}

$report="$env:GITHUB_WORKSPACE\xg-top5-v10-report.txt"
'XG Top5 Rollout v10 Explicit Preset Prompt Geometry'|Out-File $report
$script:xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$script:xg.Refresh();if($script:xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
$hwnd=[IntPtr]$script:xg.MainWindowHandle;$main=[R10N]::GetMenu($hwnd);$analyze=[R10N]::GetSubMenu($main,4);$positionId=[R10N]::GetMenuItemID($analyze,1)
if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position command unavailable'}
[R10N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250;[void][R10N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Post 'xg-top5-v10/position-command' 'success' 'Analyze Position sent';Start-Sleep 15

$wr=New-Object R10N+RECT;if(-not[R10N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$width=$wr.Right-$wr.Left;$height=$wr.Bottom-$wr.Top
"WINDOW_RECT: $($wr.Left),$($wr.Top),$($wr.Right),$($wr.Bottom)"|Out-File $report -Append
if($width-ne924 -or $height-ne668){throw "Unexpected XG window geometry ${width}x${height}; refusing coordinate rollout selection"}
$x=[int]$wr.Left+130;$ys=@(([int]$wr.Top+370),([int]$wr.Top+413),([int]$wr.Top+456),([int]$wr.Top+499),([int]$wr.Top+542))
LeftClick $x $ys[0];[R10N]::keybd_event(0x11,0,0,[UIntPtr]::Zero);try{for($i=1;$i-lt5;$i++){LeftClick $x $ys[$i]}}finally{[R10N]::keybd_event(0x11,0,2,[UIntPtr]::Zero)}
Start-Sleep -Milliseconds 500;Shot 'xg-top5-v10-selected-five'

$subOrigin=HoverRollout $x $ys[4]
Shot 'xg-top5-v10-submenu-before-preset'
$subX=[int]$subOrigin[0];$subY=[int]$subOrigin[1]
# Proven v8 submenu: first preset center offset 12, then 19px rows. Fourth preset center = +69px.
$presetX=$subX+167;$presetY=$subY+69
"PRESET4_CLICK_POINT: $presetX,$presetY"|Out-File $report -Append
LeftClick $presetX $presetY
'PRESET4_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v10/preset4' 'success' 'Explicit fourth rollout preset clicked'
Start-Sleep -Milliseconds 700

$subOrigin2=HoverRollout $x $ys[4]
Shot 'xg-top5-v10-submenu-after-preset'
$subX2=[int]$subOrigin2[0];$subY2=[int]$subOrigin2[1]
# Proven v8 Start center = submenu top +240px.
$startX=$subX2+167;$startY=$subY2+240
"START_CLICK_POINT: $startX,$startY"|Out-File $report -Append
LeftClick $startX $startY
'START_CLICKED_AFTER_PRESET4: True'|Out-File $report -Append
Post 'xg-top5-v10/start' 'success' 'Start clicked after explicit preset4'
Start-Sleep 1;Shot 'xg-top5-v10-prompt-1s';DumpDesktop 'xg-top5-v10-prompt-1s'
Start-Sleep 2;Shot 'xg-top5-v10-prompt-3s';DumpDesktop 'xg-top5-v10-prompt-3s'
'PROMPT_CAPTURED_NO_CONFIRMATION: True'|Out-File $report -Append
Post 'xg-top5-v10/prompt' 'success' 'Prompt captured without confirmation'
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
