$ErrorActionPreference='Stop'
$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-run-midgame-xgrpp-export-v15.ps1'
$src=Get-Content $srcPath -Raw

$oldDialog=@'
function FindSaveGameAutomationDialog(){
  try{
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Save Game')
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Children,$nameCond)
  }catch{return $null}
}
function InvokeAutomationNo([System.Windows.Automation.AutomationElement]$dialog){
  if($null-eq$dialog){return $false}
  try{
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')
    $button=$dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$nameCond)
    if($null-eq$button){return $false}
    $pattern=$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if($null-eq$pattern){return $false}
    $pattern.Invoke()
    return $true
  }catch{return $false}
}
'@

$newDialog=@'
function FindSaveGameAutomationDialog(){
  try{
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Save Game')
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$nameCond)
    foreach($candidate in $all){
      try{
        if([string]$candidate.Current.Name -eq 'Save Game' -and $candidate.Current.IsEnabled){return $candidate}
      }catch{}
    }
  }catch{}
  return $null
}
function InvokeAutomationNo([System.Windows.Automation.AutomationElement]$dialog){
  if($null-eq$dialog){return $false}
  try{
    $nameCond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'No')
    $buttons=$dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants,$nameCond)
    foreach($button in $buttons){
      try{
        if([string]$button.Current.Name -ne 'No' -or -not$button.Current.IsEnabled){continue}
        try{
          $pattern=$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          if($null-ne$pattern){$pattern.Invoke();return $true}
        }catch{}
        $r=$button.Current.BoundingRectangle
        if($r.Width-gt0 -and $r.Height-gt0){
          LeftClick ([int]($r.X+$r.Width/2)) ([int]($r.Y+$r.Height/2))
          return $true
        }
      }catch{}
    }
  }catch{}
  return $false
}
'@

if(-not$src.Contains($oldDialog)){throw 'v15 Save Game automation block not found'}
$src=$src.Replace($oldDialog,$newDialog)

$oldBaseline=@'
$baseline=ExportText
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
$beforeSource=TopSource $baseline
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source'}
'@

$newBaseline=@'
$baseline=''
$beforeSource=''
for($baselineAttempt=1;$baselineAttempt-le3 -and -not$beforeSource;$baselineAttempt++){
  $baseline=ExportText
  $beforeSource=TopSource $baseline
  $looksLikeXgid=$baseline.Trim().StartsWith('XGID=')
  "BASELINE_ATTEMPT_${baselineAttempt}_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_SOURCE: $beforeSource"|Out-File $report15 -Append
  "BASELINE_ATTEMPT_${baselineAttempt}_XGID_ONLY: $looksLikeXgid"|Out-File $report15 -Append
  if($beforeSource){break}
  if($looksLikeXgid -or $baseline.Length-lt100){
    $retryDismissed=DismissDelayedSaveGame
    "BASELINE_ATTEMPT_${baselineAttempt}_SAVE_DISMISSED: $retryDismissed"|Out-File $report15 -Append
    if($retryDismissed){Post 'xg-public-v17/save-dialog-dismissed' 'success' "Save Game dismissed on baseline attempt $baselineAttempt"}
    InvokeAnalyzePosition
    Post 'xg-public-v17/midgame-analyze-retry' 'success' "baseline attempt $baselineAttempt reissued Analyze Position"
    Start-Sleep 20
    Shot "$env:GITHUB_WORKSPACE\xg-v17-baseline-retry-${baselineAttempt}.png"
  }
}
Set-Content "$env:GITHUB_WORKSPACE\xg-v15-before-xgrpp.txt" $baseline -Encoding UTF8
"TOP_SOURCE_BEFORE_XGRPP: $beforeSource"|Out-File $report15 -Append
"BASELINE_CLIPBOARD_LENGTH: $($baseline.Length)"|Out-File $report15 -Append
if(-not$beforeSource){throw 'Could not parse baseline top candidate source after v17 dialog recovery'}
'@

if(-not$src.Contains($oldBaseline)){throw 'v15 baseline block not found'}
$src=$src.Replace($oldBaseline,$newBaseline)
$tmp=Join-Path $env:RUNNER_TEMP 'xg-v17-patched.ps1'
Set-Content $tmp $src -Encoding UTF8
& $tmp
