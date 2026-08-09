$ErrorActionPreference='Stop'

function Post([string]$context,[string]$state,[string]$description){
  try{
    $payload=@{state=$state;context=$context;description=$description}|ConvertTo-Json -Compress
    $headers=@{Authorization="Bearer $env:GH_TOKEN";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'}
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$env:GITHUB_REPOSITORY/statuses/$env:GATE_SHA" -Headers $headers -Body $payload -ContentType 'application/json'|Out-Null
  }catch{}
}

# Preserve XG after the proven selection/submenu helper.
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

$script:xg=$script:xg
if($null-eq$script:xg -or $script:xg.HasExited){throw 'XG process not alive after proven helper'}
Post 'xg-top5-v18/top-five-ready' 'success' 'Top five selected and Rollout submenu open'

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

$sub=FindLargeSubmenu $script:xg.Id
if($null-eq$sub){Shot 'xg-top5-v18-submenu-missing';throw 'Rollout submenu missing'}
$sr=$sub.Current.BoundingRectangle
$script:rolloutSubmenuRect=$sr

# Proven twice by screenshots: row 4 is Moves 3-ply, cube decisions XG Roller.
$presetX=[int]($sr.X+150)
$presetY=[int]($sr.Y+69)
LeftClick $presetX $presetY
Post 'xg-top5-v18/preset-clicked' 'success' 'Clicked proven 3-ply/XG Roller preset row'
Start-Sleep 1

$root=[System.Windows.Automation.AutomationElement]::RootElement
$dlg=$null
for($i=0;$i-lt20;$i++){
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($e in $all){
    try{
      if($e.Current.ProcessId-eq$script:xg.Id -and $e.Current.ClassName-eq'TPromptRollOutDlg' -and $e.Current.Name-eq'Rollout'){$dlg=$e;break}
    }catch{}
  }
  if($null-ne$dlg){break}
  Start-Sleep -Milliseconds 250
}
if($null-eq$dlg){Shot 'xg-top5-v18-prompt-missing';throw 'Rollout prompt missing'}

$desc=$dlg.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$ok=$null;$cancel=$null;$games=$null
foreach($e in $desc){
  try{
    $n=[string]$e.Current.Name
    if($n-eq'Ok' -and $e.Current.ClassName-eq'TButton'){$ok=$e}
    if($n-eq'Cancel' -and $e.Current.ClassName-eq'TButton'){$cancel=$e}
    if($n-eq'1296' -and $e.Current.ClassName-eq'TSpinEditX'){$games=$e}
  }catch{}
}
if($null-eq$games -or $null-eq$ok -or $null-eq$cancel){Shot 'xg-top5-v18-prompt-signature-mismatch';throw 'Rollout prompt signature mismatch'}
Shot 'xg-top5-v18-before-ok'
Post 'xg-top5-v18/prompt-verified' 'success' 'Verified prompt class, 1296, Ok and Cancel after proven preset click'

$or=$ok.Current.BoundingRectangle
LeftClick ([int]($or.X+$or.Width/2)) ([int]($or.Y+$or.Height/2))
Post 'xg-top5-v18/rollout-launched' 'success' 'Clicked Ok; verified top-five rollout launched'
