param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$CasesPath,
  [Parameter(Mandatory=$true)][string]$OutDir
)

$ErrorActionPreference='Stop'
$workspace=$env:GITHUB_WORKSPACE
if(-not $workspace){$workspace=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'raw') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'screens') | Out-Null

$cases=Get-Content $CasesPath -Raw | ConvertFrom-Json
if($cases.Count -ne 24){throw "Expected 24 parity cases, got $($cases.Count)"}

# Reuse the public runner's already-proven first-run startup through the point where
# a Position.xgp XGID is loaded. No activation/licensing behavior is modified here.
$v1Path=Join-Path $workspace '.github\workflows\xg-analyze-level-public-v1.yml'
$v1=Get-Content $v1Path -Raw
$m=[regex]::Match($v1,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not $m.Success){throw 'Could not extract proven public v1 startup'}
$startup=$m.Groups['script'].Value -replace '(?m)^          ',''
$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$startup.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'XGID_POSITION_READY marker missing from proven startup'}
$prefix=$startup.Substring(0,$idx+$marker.Length)

$tail=@'

# ---------------- Zand/XG cube parity batch ----------------
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ZParityN {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu,int nPos);
  [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd,IntPtr hMenu,uint uItem,out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
"@

function ClickXY([int]$x,[int]$y){
  [ZParityN]::SetCursorPos($x,$y)|Out-Null
  Start-Sleep -Milliseconds 120
  [ZParityN]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 60
  [ZParityN]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
function Shot([string]$path){
  try{
    $b=[System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height
    $g=[System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size)
    $bmp.Save($path,[System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose();$bmp.Dispose()
  }catch{}
}
function FindSaveGameDialog(){
  try{
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($w in $all){
      try{if($w.Current.ProcessId-eq$xg.Id -and $w.Current.Name-eq'Save Game'){return $w}}catch{}
    }
  }catch{}
  return $null
}
function DismissSaveGame(){
  $deadline=(Get-Date).AddSeconds(8)
  while((Get-Date)-lt$deadline){
    $d=FindSaveGameDialog
    if($null-ne$d){
      try{
        $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')
        $b=$d.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cond)
        if($null-ne$b){
          $p=$b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          $p.Invoke();Start-Sleep -Milliseconds 700;return $true
        }
      }catch{}
    }
    Start-Sleep -Milliseconds 250
  }
  return $false
}
function LoadXgid([string]$xgid){
  Set-Clipboard -Value $xgid
  Start-Sleep -Milliseconds 150
  $xg.Refresh()
  [ZParityN]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 180
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  Start-Sleep -Milliseconds 600
  [void](DismissSaveGame)
  # Re-paste after the unsaved-position transition, matching the proven midgame seam.
  Set-Clipboard -Value $xgid
  $xg.Refresh()
  [ZParityN]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 180
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  $deadline=(Get-Date).AddSeconds(12)
  while((Get-Date)-lt$deadline){
    Start-Sleep -Milliseconds 400
    $xg.Refresh()
    if($xg.HasExited){throw 'XG exited while loading parity XGID'}
    if($xg.MainWindowTitle-like'*Position.xgp*'){return $true}
    [void](DismissSaveGame)
  }
  return $false
}
function InvokeAnalyzePosition(){
  $xg.Refresh()
  $hwnd=[IntPtr]$xg.MainWindowHandle
  $menu=[ZParityN]::GetMenu($hwnd)
  $top=New-Object ZParityN+RECT
  if(-not[ZParityN]::GetMenuItemRect($hwnd,$menu,4,[ref]$top)){throw 'Analyze top rect failed'}
  [ZParityN]::SetForegroundWindow($hwnd)|Out-Null
  Start-Sleep -Milliseconds 180
  ClickXY ([int](($top.Left+$top.Right)/2)) ([int](($top.Top+$top.Bottom)/2))
  Start-Sleep -Milliseconds 300
  $sub=[ZParityN]::GetSubMenu($menu,4)
  $pos=New-Object ZParityN+RECT
  if(-not[ZParityN]::GetMenuItemRect($hwnd,$sub,1,[ref]$pos)){throw 'Analyze Position row rect failed'}
  ClickXY ([int](($pos.Left+$pos.Right)/2)) ([int](($pos.Top+$pos.Bottom)/2))
}
function ExportText(){
  $xg.Refresh()
  [ZParityN]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
  Start-Sleep -Milliseconds 180
  [System.Windows.Forms.SendKeys]::SendWait('^c')
  Start-Sleep -Milliseconds 500
  try{return [string](Get-Clipboard -Raw -TextFormatType Text)}catch{return [string](Get-Clipboard -Raw)}
}
function HasCubeAnalysis([string]$text){
  if([string]::IsNullOrWhiteSpace($text)){return $false}
  return (($text-match'Best Cube action:') -or (($text-match'Cubeful Equities') -and ($text-match'No double:')))
}

$cases=Get-Content $env:ZPARITY_CASES -Raw|ConvertFrom-Json
$out=$env:ZPARITY_OUT
$statusPath=Join-Path $out 'capture-status.jsonl'
if(Test-Path $statusPath){Remove-Item $statusPath -Force}
$batchStart=Get-Date
$successCount=0

foreach($c in $cases){
  $row=[ordered]@{
    case_id=[string]$c.case_id
    group=[string]$c.group
    xgid=[string]$c.xgid
    match_length=[int]$c.match_length
    score_self=[int]$c.score_self
    score_opp=[int]$c.score_opp
    crawford=[int]$c.crawford
    cube_value=[int]$c.cube_value
    cube_owner=[int]$c.cube_owner
    loaded=$false
    analyzed=$false
    cube_analysis_found=$false
    export_length=0
    elapsed_seconds=0
    error=''
  }
  $caseStart=Get-Date
  try{
    $loaded=LoadXgid ([string]$c.xgid)
    $row.loaded=$loaded
    if(-not$loaded){throw 'Position.xgp title not reached'}

    InvokeAnalyzePosition
    $row.analyzed=$true
    Start-Sleep 2
    if(DismissSaveGame){InvokeAnalyzePosition;Start-Sleep 2}

    $text=''
    $found=$false
    for($wait=5;$wait-le40 -and -not$found;$wait+=5){
      Start-Sleep 5
      $xg.Refresh()
      if($xg.HasExited){throw 'XG exited during position analysis'}
      if($xg.Responding){
        $candidate=ExportText
        if($candidate.Length-gt$text.Length){$text=$candidate}
        if(HasCubeAnalysis $candidate){$text=$candidate;$found=$true}
      }
      if(DismissSaveGame){InvokeAnalyzePosition}
    }
    $safe=([string]$c.case_id -replace '[^A-Za-z0-9_.-]','_')
    $rawPath=Join-Path (Join-Path $out 'raw') ($safe+'.txt')
    Set-Content $rawPath $text -Encoding UTF8
    $row.export_length=$text.Length
    $row.cube_analysis_found=$found
    if($found){$successCount++}else{Shot (Join-Path (Join-Path $out 'screens') ($safe+'-no-cube-analysis.png'))}
  }catch{
    $row.error=$_.Exception.Message
    $safe=([string]$c.case_id -replace '[^A-Za-z0-9_.-]','_')
    Shot (Join-Path (Join-Path $out 'screens') ($safe+'-error.png'))
  }
  $row.elapsed_seconds=[math]::Round(((Get-Date)-$caseStart).TotalSeconds,3)
  ($row|ConvertTo-Json -Compress)|Out-File $statusPath -Append -Encoding utf8
}

$summary=[ordered]@{
  schema='zand-xg-cube-parity-capture-v1'
  requested=$cases.Count
  cube_analysis_found=$successCount
  failed_or_partial=$cases.Count-$successCount
  total_seconds=[math]::Round(((Get-Date)-$batchStart).TotalSeconds,3)
  analysis_level='installed default / public-runner controlled Analyze Position'
  training_eligible=$false
  purpose='runtime differential parity only'
}
$summary|ConvertTo-Json -Depth 4|Set-Content (Join-Path $out 'capture-summary.json') -Encoding UTF8
Get-Content (Join-Path $out 'capture-summary.json')
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@

$env:xgexe=$ExePath
$env:ZPARITY_CASES=(Resolve-Path $CasesPath).Path
$env:ZPARITY_OUT=(Resolve-Path $OutDir).Path
$tempRoot=$env:RUNNER_TEMP
if(-not$tempRoot){$tempRoot=$OutDir}
$combined=Join-Path $tempRoot 'zand-xg-cube-parity-combined.ps1'
Set-Content $combined ($prefix+$tail) -Encoding UTF8
& $combined
