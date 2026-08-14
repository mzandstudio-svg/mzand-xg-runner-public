param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
if(-not $workspace){$workspace=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Reuse the already-proven first-run/XGID startup from public v1. Stop at the
# moment the known XGID position is ready, then append read-only runtime probes.
$v1=Get-Content (Join-Path $workspace '.github\workflows\xg-analyze-level-public-v1.yml') -Raw
$m=[regex]::Match($v1,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not $m.Success){throw 'Could not extract proven v1 startup'}
$script=$m.Groups['script'].Value -replace '(?m)^          ',''
$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$script.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'XGID_POSITION_READY marker missing in proven v1 startup'}
$prefix=$script.Substring(0,$idx+$marker.Length)

$probe=@'

# ---------- XG cube/MET runtime probe ----------
$ErrorActionPreference='Stop'
$OutDir=$env:MZ_CUBE_MET_OUT
$env:XG_EXE=$env:MZ_XG_EXE
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class MZMenuProbe {
 [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
 [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetMenuString(IntPtr hMenu,uint uIDItem,StringBuilder lpString,int nMaxCount,uint uFlag);
 [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu,int nPos);
 [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr hMenu,int nPos);
 [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd,uint Msg,IntPtr wParam,IntPtr lParam);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
function MText([IntPtr]$h,[int]$pos){$sb=New-Object System.Text.StringBuilder 512;[void][MZMenuProbe]::GetMenuString($h,[uint32]$pos,$sb,$sb.Capacity,0x400);return [string]$sb.ToString()}
function MNorm([string]$s){if($null-eq$s){return ''};return ((($s-replace '&','')-split "`t")[0]).Trim()}
function DumpMenu([IntPtr]$h,[string]$path,[int]$depth=0){
 $lines=New-Object 'System.Collections.Generic.List[string]';if($h-eq[IntPtr]::Zero){return $lines};$n=[MZMenuProbe]::GetMenuItemCount($h)
 for($i=0;$i-lt$n;$i++){$raw=MText $h $i;$name=MNorm $raw;$id=[MZMenuProbe]::GetMenuItemID($h,$i);$sub=[MZMenuProbe]::GetSubMenu($h,$i);$lines.Add("$path/$i`t$name`t$id`t$sub");if($sub-ne[IntPtr]::Zero-and$depth-lt5){foreach($x in (DumpMenu $sub "$path/$name" ($depth+1))){$lines.Add($x)}}};return $lines
}
function FindMenuCommand([IntPtr]$h,[string]$target,[string]$path='ROOT',[int]$depth=0){
 if($h-eq[IntPtr]::Zero-or$depth-gt5){return $null};$n=[MZMenuProbe]::GetMenuItemCount($h)
 for($i=0;$i-lt$n;$i++){$name=MNorm(MText $h $i);$id=[MZMenuProbe]::GetMenuItemID($h,$i);$sub=[MZMenuProbe]::GetSubMenu($h,$i);if($name-eq$target-and$id-ne[uint32]0xFFFFFFFF){return @{Name=$name;Id=$id;Path="$path/$name"}};if($sub-ne[IntPtr]::Zero){$r=FindMenuCommand $sub $target "$path/$name" ($depth+1);if($r){return $r}}};return $null
}
function InvokeMenuExact([IntPtr]$hwnd,[string]$name){$menu=[MZMenuProbe]::GetMenu($hwnd);$r=FindMenuCommand $menu $name;if(-not$r){return $false};[MZMenuProbe]::SetForegroundWindow($hwnd)|Out-Null;[void][MZMenuProbe]::SendMessage($hwnd,0x0111,[IntPtr]([int]$r.Id),[IntPtr]::Zero);return $true}
function DumpTopWindows([string]$tag){
 $root=[System.Windows.Automation.AutomationElement]::RootElement;$L=New-Object 'System.Collections.Generic.List[string]';$tops=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
 foreach($tw in $tops){try{if($tw.Current.ProcessId-eq$xg.Id){$L.Add("TOP Name=[$($tw.Current.Name)] Class=[$($tw.Current.ClassName)] Id=[$($tw.Current.AutomationId)] Handle=[$($tw.Current.NativeWindowHandle)]");$all=$tw.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition);foreach($c in $all){try{$r=$c.Current.BoundingRectangle;$L.Add("  Name=[$($c.Current.Name)] Type=[$($c.Current.ControlType.ProgrammaticName)] Id=[$($c.Current.AutomationId)] Class=[$($c.Current.ClassName)] Enabled=[$($c.Current.IsEnabled)] Bounds=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")}catch{}}}}catch{}}
 $L|Out-File (Join-Path $OutDir "$tag-ui.txt") -Encoding utf8
}
$probeReport=Join-Path $OutDir 'report.txt'
'XG_CUBE_MET_RUNTIME_PROBE_V1'|Out-File $probeReport
"EXE=$env:XG_EXE"|Out-File $probeReport -Append
$xg.Refresh();$hwnd=[IntPtr]$xg.MainWindowHandle
"MAIN_TITLE=$($xg.MainWindowTitle)"|Out-File $probeReport -Append
"MAIN_HWND=$hwnd"|Out-File $probeReport -Append

$install=Split-Path -Parent $env:XG_EXE
$metFiles=Get-ChildItem $install -Recurse -Filter *.met -File -ErrorAction SilentlyContinue
$metLines=New-Object 'System.Collections.Generic.List[string]'
foreach($f in $metFiles){
 $sha=(Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant();$txt=Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue;$name='';$ver='';$desc='';$post='';$pre=''
 if($txt-match'(?mi)^Name=(.*)$'){$name=$Matches[1].Trim()};if($txt-match'(?mi)^Version=(.*)$'){$ver=$Matches[1].Trim()};if($txt-match'(?mi)^Description=(.*)$'){$desc=$Matches[1].Trim()};if($txt-match'(?ms)\[PostCrawford\].*?^Size=(\d+)'){$post=$Matches[1]};if($txt-match'(?ms)\[PreCrawford\].*?^Size=(\d+)'){$pre=$Matches[1]}
 $rel=$f.FullName.Substring($install.Length).TrimStart('\');$metLines.Add("FILE=$rel`tSHA256=$sha`tNAME=$name`tVERSION=$ver`tDESC=$desc`tPOST=$post`tPRE=$pre")
}
$metLines|Out-File (Join-Path $OutDir 'installed-met-inventory.txt') -Encoding utf8
"MET_COUNT=$($metFiles.Count)"|Out-File $probeReport -Append

$regOut=New-Object 'System.Collections.Generic.List[string]'
foreach($rootKey in @('HKCU:\Software','HKLM:\Software','HKLM:\Software\WOW6432Node')){try{Get-ChildItem $rootKey -Recurse -ErrorAction SilentlyContinue|Where-Object{$_.Name-match'eXtreme|Gammon|GameSite'}|ForEach-Object{try{$p=Get-ItemProperty $_.PSPath -ErrorAction Stop;foreach($prop in $p.PSObject.Properties){if($prop.Name-notmatch'^PS'-and(($prop.Name-match'MET|Cube|Crawford|Jacoby|Beaver|Double|Analyze|Search|Level')-or([string]$prop.Value-match'MET|Kazaross|Cube|Crawford|Jacoby|Beaver'))){$regOut.Add("$($_.Name)`t$($prop.Name)=$($prop.Value)")}}}catch{}}}catch{}}
$regOut|Sort-Object -Unique|Out-File (Join-Path $OutDir 'registry-cube-met.txt') -Encoding utf8

$menu=[MZMenuProbe]::GetMenu($hwnd);DumpMenu $menu 'ROOT'|Out-File (Join-Path $OutDir 'menu-tree.txt') -Encoding utf8
foreach($wanted in @('Match Equity Table','Cube Information','Load MET')){$r=FindMenuCommand $menu $wanted;if($r){"MENU_$($wanted.Replace(' ','_'))=$($r.Path);ID=$($r.Id)"|Out-File $probeReport -Append}else{"MENU_$($wanted.Replace(' ','_'))=NOT_FOUND"|Out-File $probeReport -Append}}

if(InvokeMenuExact $hwnd 'Match Equity Table'){Start-Sleep 2;DumpTopWindows 'match-equity-table';Snap 'cube-met-match-equity-table';'MATCH_EQUITY_TABLE_OPENED=True'|Out-File $probeReport -Append;[System.Windows.Forms.SendKeys]::SendWait('{ESC}');Start-Sleep -Milliseconds 500}else{'MATCH_EQUITY_TABLE_OPENED=False'|Out-File $probeReport -Append}
if(InvokeMenuExact $hwnd 'Cube Information'){Start-Sleep 2;DumpTopWindows 'cube-information';Snap 'cube-met-cube-information';'CUBE_INFORMATION_OPENED=True'|Out-File $probeReport -Append;[System.Windows.Forms.SendKeys]::SendWait('{ESC}');Start-Sleep -Milliseconds 500}else{'CUBE_INFORMATION_OPENED=False'|Out-File $probeReport -Append}
$xg.Refresh();"XG_RESPONDING=$($xg.Responding)"|Out-File $probeReport -Append
Get-Content $probeReport
Get-Process|Where-Object{$_.ProcessName-match'^eXtremeGammon2$|^test3d$'}|Stop-Process -Force -ErrorAction SilentlyContinue
'@

$env:MZ_CUBE_MET_OUT=$OutDir
$env:MZ_XG_EXE=$ExePath
$temp=Join-Path $env:RUNNER_TEMP 'mz-xg-cube-met-combined.ps1'
Set-Content $temp ($prefix+$probe) -Encoding UTF8
& $temp
