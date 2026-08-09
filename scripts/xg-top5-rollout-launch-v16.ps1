$ErrorActionPreference='Stop'

function Post([string]$context,[string]$state,[string]$description){
  try{
    $payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress
    $headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'}
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null
  }catch{}
}

# Keep XG alive after the proven helper finishes.
function Stop-Process {
  [CmdletBinding()]
  param(
    [Parameter(ValueFromPipeline=$true)]$InputObject,
    [string[]]$Name,
    [int[]]$Id,
    [switch]$Force
  )
  process { }
}
. ./scripts/xg-top5-rollout-submenu-probe.ps1
Remove-Item Function:\Stop-Process -Force

$report="$env:GITHUB_WORKSPACE\xg-top5-v16-report.txt"
'XG Top5 Rollout v16 Launch'|Out-File $report
$xg=$script:xg
if($null-eq$xg -or $xg.HasExited){throw 'XG process not alive after proven helper'}
Post 'xg-top5-v16/top-five-ready' 'success' 'Top five moves selected; Rollout submenu open'

function FindLargeSubmenu([int]$processId){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $hits=@()
  foreach($e in $all){
    try{
      $r=$e.Current.BoundingRectangle
      if($e.Current.ProcessId-eq$processId -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt300 -and $r.Height-gt300){$hits+=,$e}
    }catch{}
  }
  if($hits.Count-ne1){return $null}
  return $hits[0]
}
function DumpXG([string]$name,[int]$processId){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $lines=New-Object 'System.Collections.Generic.List[string]'
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-eq$processId){
        $r=$e.Current.BoundingRectangle
        $lines.Add("Name=[$($e.Current.Name)] Type=[$($e.Current.ControlType.ProgrammaticName)] Class=[$($e.Current.ClassName)] Id=[$($e.Current.AutomationId)] Enabled=[$($e.Current.IsEnabled)] Rect=[$($r.X),$($r.Y),$($r.Width),$($r.Height)]")
      }
    }catch{}
  }
  $lines|Out-File "$env:GITHUB_WORKSPACE\$name-ui.txt" -Encoding utf8
}

$sub=FindLargeSubmenu $xg.Id
if($null-eq$sub){Shot 'xg-top5-v16-submenu-missing';throw 'Rollout submenu missing'}
$sr=$sub.Current.BoundingRectangle
"ROLLOUT_SUBMENU_RECT: $($sr.X),$($sr.Y),$($sr.Width),$($sr.Height)"|Out-File $report -Append

# Proven by v15 artifact: clicking row 4 directly opens the rollout duration prompt.
$presetX=[int]($sr.X+150)
$presetY=[int]($sr.Y+69)
LeftClick $presetX $presetY
"PRESET_CLICK_POINT: $presetX,$presetY"|Out-File $report -Append
Post 'xg-top5-v16/preset-clicked' 'success' 'Clicked Moves 3-ply, cube decisions XG Roller preset'
Start-Sleep 1

$root=[System.Windows.Automation.AutomationElement]::RootElement
$dlg=$null
for($i=0;$i-lt20;$i++){
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'TPromptRollOutDlg' -and $e.Current.Name-eq'Rollout'){$dlg=$e;break}
    }catch{}
  }
  if($null-ne$dlg){break}
  Start-Sleep -Milliseconds 250
}
if($null-eq$dlg){Shot 'xg-top5-v16-prompt-missing';throw 'Expected Rollout prompt did not appear'}

$desc=$dlg.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$ok=$null;$cancel=$null;$games=$null;$presetText=$null
foreach($e in $desc){
  try{
    $n=[string]$e.Current.Name
    if($n-eq'Ok' -and $e.Current.ClassName-eq'TButton'){$ok=$e}
    if($n-eq'Cancel' -and $e.Current.ClassName-eq'TButton'){$cancel=$e}
    if($n-eq'1296' -and $e.Current.ClassName-eq'TSpinEditX'){$games=$e}
    if($n-like'*Moves 3-ply, cube decisions XG Roller*'){$presetText=$n}
  }catch{}
}
"PROMPT_PRESET_TEXT: $presetText"|Out-File $report -Append
"PROMPT_1296_FOUND: $($null-ne$games)"|Out-File $report -Append
"PROMPT_OK_FOUND: $($null-ne$ok)"|Out-File $report -Append
"PROMPT_CANCEL_FOUND: $($null-ne$cancel)"|Out-File $report -Append
if($null-eq$presetText -or $null-eq$games -or $null-eq$ok -or $null-eq$cancel){Shot 'xg-top5-v16-prompt-signature-mismatch';DumpXG 'xg-top5-v16-prompt-signature-mismatch' $xg.Id;throw 'Rollout prompt is not the proven 3-ply/XG Roller/1296 signature'}
Shot 'xg-top5-v16-before-ok'
DumpXG 'xg-top5-v16-before-ok' $xg.Id
Post 'xg-top5-v16/prompt-verified' 'success' 'Verified 3-ply/XG Roller preset and 1296 games'

$or=$ok.Current.BoundingRectangle
$okX=[int]($or.X+$or.Width/2);$okY=[int]($or.Y+$or.Height/2)
LeftClick $okX $okY
"OK_CLICK_POINT: $okX,$okY"|Out-File $report -Append
'ROLLOUT_OK_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v16/rollout-launched' 'success' 'Clicked Ok on verified rollout prompt'

Start-Sleep 1
Shot 'xg-top5-v16-rollout-1s';DumpXG 'xg-top5-v16-rollout-1s' $xg.Id
Start-Sleep 4
Shot 'xg-top5-v16-rollout-5s';DumpXG 'xg-top5-v16-rollout-5s' $xg.Id
Start-Sleep 15
Shot 'xg-top5-v16-rollout-20s';DumpXG 'xg-top5-v16-rollout-20s' $xg.Id
$xg.Refresh()
"XG_HAS_EXITED_20S: $($xg.HasExited)"|Out-File $report -Append
if(-not$xg.HasExited){"XG_RESPONDING_20S: $($xg.Responding)"|Out-File $report -Append}
Post 'xg-top5-v16/progress-captured' 'success' 'Captured rollout state through 20 seconds'
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
