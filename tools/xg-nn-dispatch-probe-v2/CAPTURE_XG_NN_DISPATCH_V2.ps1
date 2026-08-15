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
if(-not $m.Success){throw 'Could not extract proven startup'}
$startup=$m.Groups['script'].Value -replace '(?m)^          ',''
$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$startup.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx -lt 0){throw 'startup marker missing'}
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
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
function Shot([string]$p){try{$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);$bmp.Save($p,[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()}catch{}}
function FindDialog([string]$name){
 $root=[System.Windows.Automation.AutomationElement]::RootElement
 $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
 foreach($w in $wins){try{if($w.Current.ProcessId -eq $xg.Id -and $w.Current.Name -eq $name){return $w}}catch{}}
 return $null
}
function SaveDialog(){return FindDialog 'Save Game'}
function DismissRegistration([double]$seconds){
 $deadline=(Get-Date).AddSeconds($seconds)
 while((Get-Date) -lt $deadline){
   $d=FindDialog 'Registration'
   if($null -eq $d){Start-Sleep -Milliseconds 150;continue}
   $b=$d.FindFirst([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Close')))
   if($null -ne $b){try{$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke();Start-Sleep -Milliseconds 800;return $true}catch{}}
   Start-Sleep -Milliseconds 150
 }
 return $false
}
function DismissSave([double]$seconds){
 $deadline=(Get-Date).AddSeconds($seconds)
 while((Get-Date) -lt $deadline){
   $d=SaveDialog
   if($null -ne $d){
     $b=$d.FindFirst([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')))
     if($null -ne $b){try{$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke();Start-Sleep -Milliseconds 700;return $true}catch{}}
   }
   Start-Sleep -Milliseconds 150
 }
 return $false
}
function FocusXg(){ $xg.Refresh(); if($xg.HasExited){throw 'XG exited'}; [D2N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null; Start-Sleep -Milliseconds 180 }
function ExportXgid(){
 $sentinel='__D2_XGID_SENTINEL__'+[guid]::NewGuid().ToString('N');Set-Clipboard -Value $sentinel
 FocusXg; [System.Windows.Forms.SendKeys]::SendWait('^+c'); Start-Sleep -Milliseconds 700
 $t=[string](Get-Clipboard -Raw); if($t -eq $sentinel){return ''}
 $m=[regex]::Match($t,'XGID=[^\r\n ]+')
 if($m.Success){return $m.Value.Trim()} return ''
}
function ImportVerified([string]$target){
 [void](DismissRegistration 4)
 Set-Clipboard -Value $target; FocusXg; [System.Windows.Forms.SendKeys]::SendWait('^v')
 $dismissed=DismissSave 6
 if($dismissed){Set-Clipboard -Value $target;FocusXg;[System.Windows.Forms.SendKeys]::SendWait('^v')}
 Start-Sleep 2
 $got=ExportXgid
 if($got -eq $target){return $got}
 [void](DismissSave 2);[void](DismissRegistration 2)
 Set-Clipboard -Value $target;FocusXg;[System.Windows.Forms.SendKeys]::SendWait('^v');Start-Sleep 2
 $got=ExportXgid
 if($got -ne $target){throw "XGID_VERIFY_MISMATCH target=[$target] got=[$got]"}
 return $got
}
function InvokeOnePly(){
 [void](DismissRegistration 2)
 FocusXg
 [System.Windows.Forms.SendKeys]::SendWait('^1')
}
function ExportFull(){
 $sentinel='__D2_FULL_SENTINEL__'+[guid]::NewGuid().ToString('N');Set-Clipboard -Value $sentinel
 FocusXg;[System.Windows.Forms.SendKeys]::SendWait('^c');Start-Sleep -Milliseconds 700
 $t=[string](Get-Clipboard -Raw);if($t -eq $sentinel){return ''};return $t
}
function HasAnalysis([string]$t){return ($t -match '(?i)1[- ]ply|Player\s*Winning Chances:|Cubeful Equities|Best Cube action:|(?m)^\s*1\.\s+')}

@('DIRECT_NN_COMMAND=Ctrl+1','XGID_VERIFY_COMMAND=Ctrl+Shift+C with fresh clipboard sentinel','POSITION_EXPORT_COMMAND=Ctrl+C with fresh clipboard sentinel','REGISTRATION_DIALOG=explicitly dismissed before import/analysis')|Out-File (Join-Path $env:D2_OUT 'probe-contract.txt') -Encoding utf8

Get-Process eXtremeGammon2 -ErrorAction SilentlyContinue|Stop-Process -Force
Start-Sleep 2
$xg=Start-Process $env:xgexe -WorkingDirectory (Split-Path -Parent $env:xgexe) -PassThru
Start-Sleep 6
$xg.Refresh()
if($xg.HasExited){throw 'XG exited after restart'}
[void](DismissRegistration 12)

$cases=Get-Content $env:D2_CASES -Raw|ConvertFrom-Json
$status=Join-Path $env:D2_OUT 'capture-status.jsonl';if(Test-Path $status){Remove-Item $status -Force}
foreach($c in $cases){
 $s=Get-Date;$row=[ordered]@{case_id=[string]$c.case_id;xgid=[string]$c.xgid;import_verified=$false;verified_xgid='';one_ply_command_sent=$false;analysis_found=$false;mentions_1ply=$false;export_length=0;elapsed_seconds=0;error=''}
 try{
   $got=ImportVerified ([string]$c.xgid);$row.import_verified=$true;$row.verified_xgid=$got
   InvokeOnePly;$row.one_ply_command_sent=$true
   Start-Sleep 2
   if(DismissSave 2){InvokeOnePly}
   $text='';$deadline=(Get-Date).AddSeconds(24)
   while((Get-Date) -lt $deadline -and -not (HasAnalysis $text)){
     Start-Sleep 2;$candidate=ExportFull;if($candidate.Length -gt $text.Length){$text=$candidate}
   }
   $safe=([string]$c.case_id -replace '[^A-Za-z0-9_.-]','_')
   Set-Content (Join-Path (Join-Path $env:D2_OUT 'raw') ($safe+'.txt')) $text -Encoding UTF8
   $row.export_length=$text.Length;$row.analysis_found=HasAnalysis $text;$row.mentions_1ply=($text -match '(?i)1[- ]ply')
   Shot (Join-Path (Join-Path $env:D2_OUT 'screens') ($safe+'.png'))
 }catch{$row.error=$_.Exception.Message;Shot (Join-Path (Join-Path $env:D2_OUT 'screens') (([string]$c.case_id)+'-error.png'))}
 $row.elapsed_seconds=[math]::Round(((Get-Date)-$s).TotalSeconds,3);($row|ConvertTo-Json -Compress)|Out-File $status -Append -Encoding utf8
}
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$env:xgexe=$ExePath;$env:D2_CASES=(Resolve-Path $CasesPath).Path;$env:D2_OUT=(Resolve-Path $OutDir).Path
$temp=Join-Path $env:RUNNER_TEMP 'xg-nn-dispatch-v2-generated.ps1';Set-Content $temp ($prefix+$tail) -Encoding UTF8;& $temp
