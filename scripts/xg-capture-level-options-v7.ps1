$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V7N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd, IntPtr hMenu, uint uItem, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
}
"@
function ClickXY([int]$x,[int]$y){[V7N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 150;[V7N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 80;[V7N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function Shot([string]$p){$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save($p,[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}
function Post([string]$context,[string]$state,[string]$description){$payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress;$headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'};Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null}

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw "Expected Position.xgp, got [$($xg.MainWindowTitle)]"}
Post 'xg-public-v7/xgid' 'success' 'Position.xgp ready'
$hwnd=[IntPtr]$xg.MainWindowHandle
$menu=[V7N]::GetMenu($hwnd)
if($menu-eq[IntPtr]::Zero){throw 'GetMenu returned zero'}
$top=New-Object V7N+RECT
if(-not[V7N]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed'}
[V7N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2))
Start-Sleep -Milliseconds 500
$sub=[V7N]::GetSubMenu($menu,4)
$setRect=New-Object V7N+RECT
if(-not[V7N]::GetMenuItemRect($hwnd,$sub,5,[ref]$setRect)){throw 'Set Analyze Level row rect failed'}
ClickXY ([int](($setRect.Left+$setRect.Right)/2)) ([int](($setRect.Top+$setRect.Bottom)/2))
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v7-level-dialog-before-dropdown.png"

# Evidence from v6: main window rectangle was 50,50,974,718 and Player 1 combo arrow center was near 789,320.
$wr=New-Object V7N+RECT
if(-not[V7N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect main failed'}
$comboX=$wr.Left+739
$comboY=$wr.Top+270
"MAIN_RECT: $($wr.Left),$($wr.Top),$($wr.Right),$($wr.Bottom)"|Out-File "$env:GITHUB_WORKSPACE\xg-v7-report.txt"
"PLAYER1_COMBO_ARROW_POINT: $comboX,$comboY"|Out-File "$env:GITHUB_WORKSPACE\xg-v7-report.txt" -Append
ClickXY $comboX $comboY
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v7-player1-level-options.png"
'PLAYER1_LEVEL_DROPDOWN_OPENED: True'|Out-File "$env:GITHUB_WORKSPACE\xg-v7-report.txt" -Append
'LEVEL_SELECTION_CHANGED: False'|Out-File "$env:GITHUB_WORKSPACE\xg-v7-report.txt" -Append
'ANALYSIS_STARTED: False'|Out-File "$env:GITHUB_WORKSPACE\xg-v7-report.txt" -Append
'ROLLOUT_STARTED: False'|Out-File "$env:GITHUB_WORKSPACE\xg-v7-report.txt" -Append
Post 'xg-public-v7/options-captured' 'success' 'Player 1 Analyze Level options screenshot captured without selection'
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
