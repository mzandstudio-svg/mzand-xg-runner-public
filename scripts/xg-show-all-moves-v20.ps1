$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V20N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd,uint Msg,IntPtr wParam,IntPtr lParam);
}
"@
function Shot([string]$name){
  $b=[System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height
  $g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size)
  $bmp.Save("$env:GITHUB_WORKSPACE\$name.png",[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()
}
function LeftClick([int]$x,[int]$y){[V20N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V20N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V20N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function RightClick([int]$x,[int]$y){[V20N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V20N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V20N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)}
function ExportText($xg){$xg.Refresh();[V20N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null;Start-Sleep -Milliseconds 250;[System.Windows.Forms.SendKeys]::SendWait('^c');Start-Sleep -Milliseconds 700;try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}}
function Parse([string]$text,[string]$stem){$txt="$env:GITHUB_WORKSPACE\$stem.txt";$json="$env:GITHUB_WORKSPACE\$stem.json";Set-Content $txt $text -Encoding UTF8;& python "$env:GITHUB_WORKSPACE\scripts\parse_xg_position_export.py" $txt $json|Out-Null;if($LASTEXITCODE-ne0){throw "parse failed $stem"};return(Get-Content $json -Raw|ConvertFrom-Json)}

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh();$hwnd=[IntPtr]$xg.MainWindowHandle
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
$main=[V20N]::GetMenu($hwnd);$analyze=[V20N]::GetSubMenu($main,4);$positionId=[V20N]::GetMenuItemID($analyze,1)
[V20N]::SetForegroundWindow($hwnd)|Out-Null;[void][V20N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Start-Sleep 15
$before=Parse (ExportText $xg) 'xg-v20-before-show-all'
"BEFORE_COUNT: $($before.candidate_count)"|Out-File "$env:GITHUB_WORKSPACE\xg-v20-report.txt"

$wr=New-Object V20N+RECT;if(-not[V20N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$rowX=[int]$wr.Left+130;$rowY=[int]$wr.Top+370
RightClick $rowX $rowY;Start-Sleep -Milliseconds 700
$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$menus=@();foreach($e in $all){try{$r=$e.Current.BoundingRectangle;if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt200 -and $r.Width-lt270 -and $r.Height-gt400 -and $r.Height-lt450){$menus+=,$e}}catch{}}
if($menus.Count-ne1){Shot 'xg-v20-context-mismatch';throw "expected one context menu got $($menus.Count)"}
$cr=$menus[0].Current.BoundingRectangle
"CONTEXT_RECT: $($cr.X),$($cr.Y),$($cr.Width),$($cr.Height)"|Out-File "$env:GITHUB_WORKSPACE\xg-v20-report.txt" -Append
# Verified context geometry: Show all Moves is centered about 374 px below menu top.
$showX=[int]($cr.X+$cr.Width/2);$showY=[int]($cr.Y+374)
"SHOW_ALL_CLICK: $showX,$showY"|Out-File "$env:GITHUB_WORKSPACE\xg-v20-report.txt" -Append
Shot 'xg-v20-before-show-all-click';LeftClick $showX $showY;Start-Sleep 2
Shot 'xg-v20-after-show-all-click'
$after=Parse (ExportText $xg) 'xg-v20-after-show-all'
"AFTER_COUNT: $($after.candidate_count)"|Out-File "$env:GITHUB_WORKSPACE\xg-v20-report.txt" -Append
"COUNT_INCREASED: $($after.candidate_count-gt$before.candidate_count)"|Out-File "$env:GITHUB_WORKSPACE\xg-v20-report.txt" -Append
if($after.candidate_count-le$before.candidate_count){throw "Show all Moves did not increase export candidates: before=$($before.candidate_count) after=$($after.candidate_count)"}
$after.candidates|ForEach-Object{"RANK=$($_.rank) MOVE=$($_.move) EQUITY=$($_.equity) METHOD=$($_.analysis_method)"}|Out-File "$env:GITHUB_WORKSPACE\xg-v20-report.txt" -Append
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
