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
public static class V11N {
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
function LeftClick([int]$x,[int]$y){[V11N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 120;[V11N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 70;[V11N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
$menu=[V11N]::GetMenu($hwnd)
if($menu-eq[IntPtr]::Zero){throw 'GetMenu returned zero'}
$top=New-Object V11N+RECT
if(-not[V11N]::GetMenuItemRect($hwnd,$menu,0,[ref]$top)){throw 'File top rect failed'}
[V11N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
LeftClick ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2))
Start-Sleep 1
Shot "$env:GITHUB_WORKSPACE\xg-v11-file-menu.png"
$sub=[V11N]::GetSubMenu($menu,0)
if($sub-eq[IntPtr]::Zero){throw 'File submenu zero'}
$count=[V11N]::GetMenuItemCount($sub)
$lines=New-Object 'System.Collections.Generic.List[string]'
for($i=0;$i-lt$count;$i++){
  $r=New-Object V11N+RECT
  if([V11N]::GetMenuItemRect($hwnd,$sub,[uint32]$i,[ref]$r)){
    $lines.Add("Index=[$i] Rect=[$($r.Left),$($r.Top),$($r.Right),$($r.Bottom)] CenterY=[$([int](($r.Top+$r.Bottom)/2))]")
  }
}
$lines|Out-File "$env:GITHUB_WORKSPACE\xg-v11-file-submenu-rects.txt" -Encoding utf8
"FILE_MENU_ITEM_COUNT: $count"|Out-File "$env:GITHUB_WORKSPACE\xg-v11-report.txt"
'FILE_MENU_CAPTURED: True'|Out-File "$env:GITHUB_WORKSPACE\xg-v11-report.txt" -Append
Post 'xg-public-v11/file-menu-captured' 'success' "File menu captured with $count geometry rows"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$generated=Join-Path $env:RUNNER_TEMP 'xg-v11-generated.ps1'
Set-Content $generated ($prefix+$tail) -Encoding UTF8
& $generated
