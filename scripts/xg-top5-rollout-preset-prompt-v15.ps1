$ErrorActionPreference='Stop'

function Post([string]$context,[string]$state,[string]$description){
  try{
    $payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress
    $headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'}
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null
  }catch{}
}

# Keep XG alive after the proven v8 helper finishes.
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

$report="$env:GITHUB_WORKSPACE\xg-top5-v15-report.txt"
'XG Top5 Rollout v15 Preset Prompt'|Out-File $report
$xg=$script:xg
if($null-eq$xg -or $xg.HasExited){throw 'XG process not alive after proven helper'}
Post 'xg-top5-v15/top-five-ready' 'success' 'Top five selected and Rollout submenu open'

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
function FindContextPopup([int]$processId){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $hits=@()
  foreach($e in $all){
    try{
      $r=$e.Current.BoundingRectangle
      if($e.Current.ProcessId-eq$processId -and $e.Current.ClassName-eq'#32768' -and $r.Width-gt200 -and $r.Width-lt280 -and $r.Height-gt390){$hits+=,$e}
    }catch{}
  }
  if($hits.Count-ne1){return $null}
  return $hits[0]
}

$sub=FindLargeSubmenu $xg.Id
if($null-eq$sub){Shot 'xg-top5-v15-initial-submenu-missing';throw 'Initial Rollout submenu missing'}
$sr=$sub.Current.BoundingRectangle
"INITIAL_SUBMENU_RECT: $($sr.X),$($sr.Y),$($sr.Width),$($sr.Height)"|Out-File $report -Append

# Explicitly select preset row 4: Moves 3-ply, cube decisions XG Roller.
$presetX=[int]($sr.X+150)
$presetY=[int]($sr.Y+69)
"PRESET_3PLY_XGROLLER_CLICK: $presetX,$presetY"|Out-File $report -Append
LeftClick $presetX $presetY
Start-Sleep -Milliseconds 700
Post 'xg-top5-v15/preset-clicked' 'success' 'Clicked preset: Moves 3-ply, cube decisions XG Roller'

# Re-open the context menu on selected move 5, then hover Rollout again.
RightClick $x $ys[4]
Start-Sleep -Milliseconds 700
$context=FindContextPopup $xg.Id
if($null-eq$context){Shot 'xg-top5-v15-context-missing';throw 'Context menu did not reopen'}
$cr=$context.Current.BoundingRectangle
"CONTEXT_RECT: $($cr.X),$($cr.Y),$($cr.Width),$($cr.Height)"|Out-File $report -Append
$rollX=[int]($cr.X+$cr.Width/2)
$rollY=[int]($cr.Y+221)
[R8N]::SetCursorPos($rollX,$rollY)|Out-Null
Start-Sleep 1
$sub2=FindLargeSubmenu $xg.Id
if($null-eq$sub2){Shot 'xg-top5-v15-submenu2-missing';throw 'Rollout submenu did not reopen'}
$sr2=$sub2.Current.BoundingRectangle
Shot 'xg-top5-v15-preset-selected-submenu'
"SECOND_SUBMENU_RECT: $($sr2.X),$($sr2.Y),$($sr2.Width),$($sr2.Height)"|Out-File $report -Append

# Click Start using the proven v8/v13 submenu geometry.
$startX=[int]($sr2.X+110)
$startY=[int]($sr2.Y+240)
LeftClick $startX $startY
'ROLLOUT_START_CLICKED: True'|Out-File $report -Append
Post 'xg-top5-v15/start-clicked' 'success' 'Clicked Rollout Start after explicit preset selection'
Start-Sleep 1

$root=[System.Windows.Automation.AutomationElement]::RootElement
$wins=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$dlg=$null;$ok=$null;$cancel=$null;$games=$null
foreach($e in $wins){
  try{
    if($e.Current.ProcessId-eq$xg.Id -and $e.Current.ClassName-eq'TPromptRollOutDlg' -and $e.Current.Name-eq'Rollout'){$dlg=$e}
  }catch{}
}
if($null-eq$dlg){Shot 'xg-top5-v15-prompt-missing';throw 'Rollout prompt did not appear'}
$desc=$dlg.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$names=New-Object 'System.Collections.Generic.List[string]'
foreach($e in $desc){
  try{
    $names.Add("Name=[$($e.Current.Name)] Class=[$($e.Current.ClassName)] Type=[$($e.Current.ControlType.ProgrammaticName)]")
    if($e.Current.Name-eq'Ok' -and $e.Current.ClassName-eq'TButton'){$ok=$e}
    if($e.Current.Name-eq'Cancel' -and $e.Current.ClassName-eq'TButton'){$cancel=$e}
    if($e.Current.Name-eq'1296' -and $e.Current.ClassName-eq'TSpinEditX'){$games=$e}
  }catch{}
}
$names|Out-File "$env:GITHUB_WORKSPACE\xg-top5-v15-prompt-ui.txt" -Encoding utf8
$dr=$dlg.Current.BoundingRectangle
"PROMPT_RECT: $($dr.X),$($dr.Y),$($dr.Width),$($dr.Height)"|Out-File $report -Append
"PROMPT_OK_FOUND: $($null-ne$ok)"|Out-File $report -Append
"PROMPT_CANCEL_FOUND: $($null-ne$cancel)"|Out-File $report -Append
"PROMPT_1296_FOUND: $($null-ne$games)"|Out-File $report -Append
if($null-eq$ok -or $null-eq$cancel -or $null-eq$games){Shot 'xg-top5-v15-prompt-signature-mismatch';throw 'Rollout prompt signature mismatch'}
Shot 'xg-top5-v15-rollout-prompt'
Post 'xg-top5-v15/prompt-captured' 'success' 'Rollout prompt captured with 1296 games; no OK click yet'
Get-Content $report
Microsoft.PowerShell.Management\Stop-Process -Name eXtremeGammon2,test3d -Force -ErrorAction SilentlyContinue
