$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class R11N {
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
function LeftClick([int]$x,[int]$y){[R11N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100;[R11N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R11N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function RightClick([int]$x,[int]$y){[R11N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100;[R11N]::mouse_event(8,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[R11N]::mouse_event(16,0,0,0,[UIntPtr]::Zero)}
function HoverRollout([int]$rowX,[int]$row5Y){RightClick $rowX $row5Y;Start-Sleep -Milliseconds 700;$contextTop=$row5Y-424;[R11N]::SetCursorPos($rowX+114,$contextTop+221)|Out-Null;Start-Sleep 1;return @((($rowX+222)),(($contextTop+209)))}
function FindUnique([string]$name,[string]$class){$root=[System.Windows.Automation.AutomationElement]::RootElement;$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition);$hits=@();foreach($e in $all){try{if($e.Current.ProcessId-eq$script:xg.Id -and [string]$e.Current.Name-eq$name -and [string]$e.Current.ClassName-eq$class){$hits+=,$e}}catch{}};if($hits.Count-eq1){return $hits[0]};return $null}

$report="$env:GITHUB_WORKSPACE\xg-top5-v11-report.txt"
'XG Top5 Rollout v11 Real 1296'|Out-File $report
$script:xg=Get-Process eXtremeGammon2 -ErrorAction Stop|Select-Object -First 1;$script:xg.Refresh()
if($script:xg.MainWindowTitle-notlike'*Position.xgp*'){throw 'Position.xgp not ready'}
$hwnd=[IntPtr]$script:xg.MainWindowHandle;$main=[R11N]::GetMenu($hwnd);$analyze=[R11N]::GetSubMenu($main,4);$positionId=[R11N]::GetMenuItemID($analyze,1)
if($positionId-eq[uint32]::MaxValue){throw 'Analyze Position command unavailable'}
[R11N]::SetForegroundWindow($hwnd)|Out-Null;Start-Sleep -Milliseconds 250;[void][R11N]::SendMessage($hwnd,0x0111,[IntPtr]([int]$positionId),[IntPtr]::Zero)
Post 'xg-top5-v11/position-command' 'success' 'Analyze Position sent';Start-Sleep 15

$wr=New-Object R11N+RECT;if(-not[R11N]::GetWindowRect($hwnd,[ref]$wr)){throw 'GetWindowRect failed'}
$width=$wr.Right-$wr.Left;$height=$wr.Bottom-$wr.Top;if($width-ne924 -or $height-ne668){throw "Unexpected XG window geometry ${width}x${height}"}
$x=[int]$wr.Left+130;$ys=@(([int]$wr.Top+370),([int]$wr.Top+413),([int]$wr.Top+456),([int]$wr.Top+499),([int]$wr.Top+542))
LeftClick $x $ys[0];[R11N]::keybd_event(0x11,0,0,[UIntPtr]::Zero);try{for($i=1;$i-lt5;$i++){LeftClick $x $ys[$i]}}finally{[R11N]::keybd_event(0x11,0,2,[UIntPtr]::Zero)}
Start-Sleep -Milliseconds 500;Shot 'xg-top5-v11-selected-five'
Post 'xg-top5-v11/top5-selected' 'success' 'First five analyzed moves selected'

$sub=HoverRollout $x $ys[4];$subX=[int]$sub[0];$subY=[int]$sub[1]
LeftClick ($subX+167) ($subY+69)
'PRESET_3PLY_XG_ROLLER_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v11/preset' 'success' 'Moves 3-ply cube XG Roller preset clicked'
Start-Sleep -Milliseconds 700
$sub2=HoverRollout $x $ys[4];$subX2=[int]$sub2[0];$subY2=[int]$sub2[1]
LeftClick ($subX2+167) ($subY2+240)
'START_CLICKED: True'|Out-File $report -Append
Start-Sleep 1;Shot 'xg-top5-v11-prompt-before-ok';DumpDesktop 'xg-top5-v11-prompt-before-ok'

$dlg=FindUnique 'Rollout' 'TPromptRollOutDlg';$games=FindUnique '1296' 'TSpinEditX';$ok=FindUnique 'Ok' 'TButton';$cancel=FindUnique 'Cancel' 'TButton'
if($null-eq$dlg -or $null-eq$games -or $null-eq$ok -or $null-eq$cancel){throw 'Expected verified 1296 Rollout prompt controls missing'}
'PROMPT_1296_VERIFIED: True'|Out-File $report -Append
$r=$ok.Current.BoundingRectangle;LeftClick ([int]($r.X+$r.Width/2)) ([int]($r.Y+$r.Height/2))
'ROLLOUT_OK_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v11/rollout-started' 'success' 'Verified 1296 rollout OK clicked'
Start-Sleep 5;Shot 'xg-top5-v11-running-5s';DumpDesktop 'xg-top5-v11-running-5s'

# Detect completion by sustained CPU idle after a minimum 45 seconds. Rollout computation is CPU-heavy; idle is only used as a gate, final UI evidence is also captured.
$elapsed=5;$idleStreak=0;$lastCpu=(Get-Process -Id $script:xg.Id).TotalProcessorTime.TotalSeconds
while($elapsed-lt1200){
  Start-Sleep 10;$elapsed+=10
  $p=Get-Process -Id $script:xg.Id -ErrorAction Stop
  $cpu=$p.TotalProcessorTime.TotalSeconds;$delta=$cpu-$lastCpu;$lastCpu=$cpu
  "CPU_DELTA_${elapsed}S: $([math]::Round($delta,3))"|Out-File $report -Append
  if($elapsed-ge45 -and $delta-lt1.0){$idleStreak++}else{$idleStreak=0}
  if($elapsed-in@(35,65,125,305,605)){Shot "xg-top5-v11-running-${elapsed}s"}
  if($idleStreak-ge3){"CPU_IDLE_COMPLETION_AT_SECONDS: $elapsed"|Out-File $report -Append;break}
}
if($idleStreak-lt3){'CPU_IDLE_COMPLETION_NOT_OBSERVED_WITHIN_1200S: True'|Out-File $report -Append}
Start-Sleep 2;$script:xg.Refresh()
"XG_RESPONDING_FINAL: $($script:xg.Responding)"|Out-File $report -Append
Shot 'xg-top5-v11-final';DumpDesktop 'xg-top5-v11-final'
'FINAL_ROLLOUT_EVIDENCE_CAPTURED: True'|Out-File $report -Append
Post 'xg-top5-v11/final-evidence' 'success' "Final rollout evidence captured at elapsed=$elapsed idleStreak=$idleStreak"
Get-Content $report
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
