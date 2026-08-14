param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$CasesPath,
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
New-Item -ItemType Directory -Force -Path $OutDir,(Join-Path $OutDir 'raw'),(Join-Path $OutDir 'screens') | Out-Null

# Reuse only the already-proven first-run initialization prefix.
$v1=Get-Content (Join-Path $workspace '.github\workflows\xg-analyze-level-public-v1.yml') -Raw
$m=[regex]::Match($v1,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not$m.Success){throw 'Could not extract proven startup'}
$startup=$m.Groups['script'].Value -replace '(?m)^          ',''
$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$startup.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'startup marker missing'}
$prefix=$startup.Substring(0,$idx+$marker.Length)

$tail=@'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class D2N {
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
 [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
 [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu,int nPos);
 [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd,IntPtr hMenu,uint uItem,out RECT r);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@
function ClickXY([int]$x,[int]$y){[D2N]::SetCursorPos($x,$y)|Out-Null;Start-Sleep -Milliseconds 100;[D2N]::mouse_event(2,0,0,0,[UIntPtr]::Zero);Start-Sleep -Milliseconds 60;[D2N]::mouse_event(4,0,0,0,[UIntPtr]::Zero)}
function Shot([string]$p){try{$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save($p,[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}catch{}}
function SaveDialog(){
 $root=[System.Windows.Automation.AutomationElement]::RootElement
 $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
 foreach($w in $wins){try{if($w.Current.ProcessId-eq$xg.Id -and $w.Current.Name-eq'Save Game'){return $w}}catch{}}
 return $null
}
function DismissSave([double]$seconds){
 $deadline=(Get-Date).AddSeconds($seconds)
 while((Get-Date)-lt$deadline){
   $d=SaveDialog
   if($null-ne$d){
     $b=$d.FindFirst([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')))
     if($null-ne$b){try{$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke();Start-Sleep -Milliseconds 700;return $true}catch{}}
   }
   Start-Sleep -Milliseconds 150
 }
 return $false
}
function FocusXg(){ $xg.Refresh(); if($xg.HasExited){throw 'XG exited'}; [D2N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null; Start-Sleep -Milliseconds 180 }
function ExportXgid(){
 FocusXg; [System.Windows.Forms.SendKeys]::SendWait('^+c'); Start-Sleep -Milliseconds 600
 $t=[string](Get-Clipboard -Raw); $m=[regex]::Match($t,'XGID=[^\r\n ]+')
 if($m.Success){return $m.Value.Trim()} return ''
}
function ImportVerified([string]$target){
 Set-Clipboard -Value $target; FocusXg; [System.Windows.Forms.SendKeys]::SendWait('^v')
 $dismissed=DismissSave 6
 if($dismissed){Set-Clipboard -Value $target;FocusXg;[System.Windows.Forms.SendKeys]::SendWait('^v')}
 Start-Sleep 2
 $got=ExportXgid
 if($got-eq$target){return $got}
 # One final exact retry after any delayed unsaved transition.
 [void](DismissSave 2)
 Set-Clipboard -Value $target;FocusXg;[System.Windows.Forms.SendKeys]::SendWait('^v');Start-Sleep 2
 $got=ExportXgid
 if($got-ne$target){throw "XGID_VERIFY_MISMATCH target=[$target] got=[$got]"}
 return $got
}
function AnalyzePosition(){
 FocusXg
 $hwnd=[IntPtr]$xg.MainWindowHandle;$menu=[D2N]::GetMenu($hwnd)
 $top=New-Object D2N+RECT;if(-not[D2N]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed'}
 ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2));Start-Sleep -Milliseconds 350
 $sub=[D2N]::GetSubMenu($menu,4);$pos=New-Object D2N+RECT;if(-not[D2N]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)){throw 'Analyze Position rect failed'}
 ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
}
function ExportFull(){FocusXg;[System.Windows.Forms.SendKeys]::SendWait('^c');Start-Sleep -Milliseconds 700;return [string](Get-Clipboard -Raw)}
function HasAnalysis([string]$t){return ($t-match'(?i)Player\s*Winning Chances:|Cubeful Equities|Best Cube action:|(?m)^\s*1\.\s+')}

# Force direct neural-network analysis level, then restart so XG cannot retain a cached level.
$settings='HKCU:\Software\GameSite 2000\eXtreme Gammon 2\Settings'
New-Item -Path $settings -Force|Out-Null
New-ItemProperty -Path $settings -Name BotAnalyzeLevel -PropertyType DWord -Value 0 -Force|Out-Null
New-ItemProperty -Path $settings -Name TopAnalyzeLevel -PropertyType DWord -Value 0 -Force|Out-Null
@('REQUESTED_LEVEL=0','BotAnalyzeLevel='+(Get-ItemPropertyValue -Path $settings -Name BotAnalyzeLevel),'TopAnalyzeLevel='+(Get-ItemPropertyValue -Path $settings -Name TopAnalyzeLevel))|Out-File (Join-Path $env:D2_OUT 'analyze-level-registry.txt') -Encoding utf8
Get-Process eXtremeGammon2 -ErrorAction SilentlyContinue|Stop-Process -Force
Start-Sleep 2
$xg=Start-Process $env:xgexe -WorkingDirectory (Split-Path -Parent $env:xgexe) -PassThru
Start-Sleep 6
$xg.Refresh()
if($xg.HasExited){throw 'XG exited after settings restart'}

$cases=Get-Content $env:D2_CASES -Raw|ConvertFrom-Json
$status=Join-Path $env:D2_OUT 'capture-status.jsonl';if(Test-Path$status){Remove-Item$status -Force}
foreach($c in $cases){
 $s=Get-Date;$row=[ordered]@{case_id=[string]$c.case_id;xgid=[string]$c.xgid;import_verified=$false;verified_xgid='';analysis_found=$false;mentions_1ply=$false;export_length=0;elapsed_seconds=0;error=''}
 try{
   $got=ImportVerified ([string]$c.xgid);$row.import_verified=$true;$row.verified_xgid=$got
   AnalyzePosition;Start-Sleep 1
   if(DismissSave 2){AnalyzePosition}
   $text='';$deadline=(Get-Date).AddSeconds(18)
   while((Get-Date)-lt$deadline -and -not(HasAnalysis $text)){
     Start-Sleep 2;$candidate=ExportFull;if($candidate.Length-gt$text.Length){$text=$candidate}
   }
   $safe=([string]$c.case_id-replace'[^A-Za-z0-9_.-]','_')
   Set-Content (Join-Path (Join-Path $env:D2_OUT 'raw') ($safe+'.txt')) $text -Encoding UTF8
   $row.export_length=$text.Length;$row.analysis_found=HasAnalysis $text;$row.mentions_1ply=($text-match'(?i)1[- ]ply')
   Shot (Join-Path (Join-Path $env:D2_OUT 'screens') ($safe+'.png'))
 }catch{$row.error=$_.Exception.Message;Shot (Join-Path (Join-Path $env:D2_OUT 'screens') (([string]$c.case_id)+'-error.png'))}
 $row.elapsed_seconds=[math]::Round(((Get-Date)-$s).TotalSeconds,3);($row|ConvertTo-Json -Compress)|Out-File $status -Append -Encoding utf8
}
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$env:xgexe=$ExePath;$env:D2_CASES=(Resolve-Path $CasesPath).Path;$env:D2_OUT=(Resolve-Path $OutDir).Path
$temp=Join-Path $env:RUNNER_TEMP 'xg-nn-dispatch-v2-generated.ps1';Set-Content $temp ($prefix+$tail) -Encoding UTF8;& $temp
