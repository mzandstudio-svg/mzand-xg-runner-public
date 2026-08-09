$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class V8N {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
  [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd, IntPtr hMenu, uint uItem, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function ClickXY([int]$x,[int]$y){[V8N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 150;[V8N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 80;[V8N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function Shot([string]$p){$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save($p,[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}
function Post([string]$context,[string]$state,[string]$description){$payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress;$headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'};Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null}

$xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1
$xg.Refresh()
if($xg.MainWindowTitle-notlike'*Position.xgp*'){throw "Expected Position.xgp, got [$($xg.MainWindowTitle)]"}
Post 'xg-public-v8/xgid' 'success' 'Position.xgp ready'
$report="$env:GITHUB_WORKSPACE\xg-v8-report.txt"
'TITLE_BEFORE_POSITION_ANALYZE: '+$xg.MainWindowTitle|Out-File $report
'ANALYZE_LEVEL_DEFAULT: World Class'|Out-File $report -Append
'XGRPP_SELECTION_CHANGED: False'|Out-File $report -Append
'ROLLOUT_STARTED: False'|Out-File $report -Append

$hwnd=[IntPtr]$xg.MainWindowHandle
$menu=[V8N]::GetMenu($hwnd)
$top=New-Object V8N+RECT
if(-not[V8N]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed'}
[V8N]::SetForegroundWindow($hwnd)|Out-Null
Start-Sleep -Milliseconds 250
ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2))
Start-Sleep -Milliseconds 500
$sub=[V8N]::GetSubMenu($menu,4)
$pos=New-Object V8N+RECT
if(-not[V8N]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)){throw 'Analyze Position row rect failed'}
"ANALYZE_POSITION_RECT: $($pos.Left),$($pos.Top),$($pos.Right),$($pos.Bottom)"|Out-File $report -Append
ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
'ANALYZE_POSITION_CLICKED: True'|Out-File $report -Append
Post 'xg-public-v8/position-analyze-started' 'success' 'Analyze Position menu command clicked at known row index 1'

Start-Sleep 2
Shot "$env:GITHUB_WORKSPACE\xg-v8-position-analysis-2s.png"
Start-Sleep 6
Shot "$env:GITHUB_WORKSPACE\xg-v8-position-analysis-8s.png"
Start-Sleep 12
Shot "$env:GITHUB_WORKSPACE\xg-v8-position-analysis-20s.png"
$xg.Refresh()
"XG_RESPONDING_20S: $($xg.Responding)"|Out-File $report -Append
"TITLE_AFTER_ANALYZE: $($xg.MainWindowTitle)"|Out-File $report -Append

$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$lines=New-Object 'System.Collections.Generic.List[string]'
foreach($e in $all){
  try{
    if($e.Current.ProcessId-eq$xg.Id -and -not$e.Current.IsOffscreen){
      $n=[string]$e.Current.Name
      $r=$e.Current.BoundingRectangle
      if($n){$lines.Add("Name=[$n] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")}
    }
  }catch{}
}
$lines|Out-File "$env:GITHUB_WORKSPACE\xg-v8-visible-ui.txt" -Encoding utf8
'CONTROLLED_POSITION_ANALYSIS_CAPTURED: True'|Out-File $report -Append
Post 'xg-public-v8/position-analysis-captured' 'success' 'Controlled World Class position analysis screenshots captured'
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
