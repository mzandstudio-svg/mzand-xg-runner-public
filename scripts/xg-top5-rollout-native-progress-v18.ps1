$ErrorActionPreference='Stop'
. ./scripts/xg-launch-top5-rollout-core-v18.ps1

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class ProgN {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
"@

$report="$env:GITHUB_WORKSPACE\xg-top5-v18-progress.txt"
'XG Top5 Rollout v18 Native Progress'|Out-File $report

function NativeText([IntPtr]$h){
  if($h-eq[IntPtr]::Zero){return ''}
  $sb=New-Object System.Text.StringBuilder 512
  [void][ProgN]::GetWindowText($h,$sb,$sb.Capacity)
  return [string]$sb.ToString()
}
function SnapshotProgress([string]$tag){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  "=== $tag ==="|Out-File $report -Append
  $barCount=0;$textCount=0
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-ne$script:xg.Id){continue}
      $cl=[string]$e.Current.ClassName
      if($cl-eq'TProgressBar'){
        $barCount++
        $h=[IntPtr]$e.Current.NativeWindowHandle
        $pos=[int][ProgN]::SendMessage($h,0x0408,[IntPtr]::Zero,[IntPtr]::Zero)
        $range=''
        try{
          $p=$e.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern)
          if($p){$range=" Range=$($p.Current.Minimum)..$($p.Current.Maximum) Value=$($p.Current.Value)"}
        }catch{}
        "BAR[$barCount] Handle=[$h] PBM_GETPOS=[$pos]$range"|Out-File $report -Append
      }
      if($cl-eq'TStaticTextX'){
        $h=[IntPtr]$e.Current.NativeWindowHandle
        $txt=NativeText $h
        if(-not[string]::IsNullOrWhiteSpace($txt)){
          $textCount++
          "TEXT[$textCount] Handle=[$h] Text=[$txt]"|Out-File $report -Append
        }
      }
    }catch{}
  }
  "COUNTS Bars=$barCount Texts=$textCount"|Out-File $report -Append
  Shot "xg-top5-v18-$tag"
}

Start-Sleep 2
SnapshotProgress 'progress-2s'
Post 'xg-top5-v18/native-2s' 'success' 'Captured native progress controls at 2s'
Start-Sleep 8
SnapshotProgress 'progress-10s'
Post 'xg-top5-v18/native-10s' 'success' 'Captured native progress controls at 10s'
Start-Sleep 20
SnapshotProgress 'progress-30s'
Post 'xg-top5-v18/native-30s' 'success' 'Captured native progress controls at 30s'
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
