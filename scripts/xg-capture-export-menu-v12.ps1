$ErrorActionPreference='Stop'
$src=Get-Content "$env:GITHUB_WORKSPACE\scripts\xg-run-position-analysis-v8.ps1" -Raw
$marker='Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue'
$idx=$src.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v8 cleanup marker missing'}
$prefix=$src.Substring(0,$idx)
$tail=@'

$xg.Refresh()
$hwnd=[IntPtr]$xg.MainWindowHandle
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V12N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
  [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd, IntPtr hMenu, uint uItem, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function LeftClick([int]$x,[int]$y){[V12N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V12N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V12N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
$main=[V12N]::GetMenu($hwnd)
if($main-eq[IntPtr]::Zero){throw 'GetMenu returned zero'}
$fileTop=New-Object V12N+RECT
if(-not[V12N]::GetMenuItemRect($hwnd,$main,0,[ref]$fileTop)){throw 'File top rect failed'}
[V12N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
LeftClick ([int](($fileTop.Left+$fileTop.Right)/2)) ([int](($fileTop.Top+$fileTop.Bottom)/2))
Start-Sleep -Milliseconds 500
$fileSub=[V12N]::GetSubMenu($main,0)
if($fileSub-eq[IntPtr]::Zero){throw 'File submenu zero'}
$exportRect=New-Object V12N+RECT
if(-not[V12N]::GetMenuItemRect($hwnd,$fileSub,8,[ref]$exportRect)){throw 'Export row rect failed'}
$ex=[int](($exportRect.Left+$exportRect.Right)/2);$ey=[int](($exportRect.Top+$exportRect.Bottom)/2)
[V12N]::SetCursorPos($ex,$ey)|Out-Null
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v12-export-submenu.png"
$exportSub=[V12N]::GetSubMenu($fileSub,8)
if($exportSub-eq[IntPtr]::Zero){throw 'Export child submenu zero'}
$count=[V12N]::GetMenuItemCount($exportSub)
$lines=New-Object 'System.Collections.Generic.List[string]'
for($i=0;$i-lt$count;$i++){
  $r=New-Object V12N+RECT
  if([V12N]::GetMenuItemRect($hwnd,$exportSub,[uint32]$i,[ref]$r)){
    $lines.Add("Index=[$i] Rect=[$($r.Left),$($r.Top),$($r.Right),$($r.Bottom)] CenterY=[$([int](($r.Top+$r.Bottom)/2))]")
  }
}
$lines|Out-File "$env:GITHUB_WORKSPACE\xg-v12-export-submenu-rects.txt" -Encoding utf8
"EXPORT_MENU_ITEM_COUNT: $count"|Out-File "$env:GITHUB_WORKSPACE\xg-v12-report.txt"
"EXPORT_ROW_POINT: $ex,$ey"|Out-File "$env:GITHUB_WORKSPACE\xg-v12-report.txt" -Append
'EXPORT_SUBMENU_CAPTURED: True'|Out-File "$env:GITHUB_WORKSPACE\xg-v12-report.txt" -Append
Post 'xg-public-v12/export-menu-captured' 'success' "Export submenu captured with $count rows"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$generated=Join-Path $env:RUNNER_TEMP 'xg-v12-generated.ps1'
Set-Content $generated ($prefix+$tail) -Encoding UTF8
& $generated
