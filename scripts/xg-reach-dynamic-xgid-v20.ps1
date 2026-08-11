$ErrorActionPreference='Stop'
if([string]::IsNullOrWhiteSpace($env:XGID_INPUT) -or -not $env:XGID_INPUT.StartsWith('XGID=')){
  throw 'XGID_INPUT is missing or invalid'
}

$yaml=Get-Content "$env:GITHUB_WORKSPACE\.github\workflows\xg-analyze-level-public-v1.yml" -Raw
$m=[regex]::Match($yaml,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not$m.Success){throw 'Could not extract public v1 proven startup'}
$script=$m.Groups['script'].Value -replace '(?m)^          ',''
$script=$script.Replace('xg-public-v1-report.txt','xg-reach-dynamic-v20-report.txt').Replace('XG public Analyze Level v1','XG reach dynamic quarantine XGID v20')

$knownLine='$xgid=''XGID=-b----E-C---eE---c-e----B-:0:0:1:51:7:10:0:11:10'''
$dynamicLine='$xgid=$env:XGID_INPUT'
if(-not$script.Contains($knownLine)){throw 'Known XGID assignment not found in proven startup'}
$script=$script.Replace($knownLine,$dynamicLine)

$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$script.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'XGID_POSITION_READY marker missing'}
$prefix=$script.Substring(0,$idx+$marker.Length)
$tail=@'

$xg.Refresh()
"XG_RESPONDING_AT_XGID: $($xg.Responding)"|Out-File $report -Append
"XG_TITLE_AT_XGID: $($xg.MainWindowTitle)"|Out-File $report -Append
"QUARANTINE_ID: $env:XGQ_ID"|Out-File $report -Append
"QUARANTINED: True"|Out-File $report -Append
"TRAINING_ELIGIBLE: False"|Out-File $report -Append
"PRISTINE_DATA_USED: False"|Out-File $report -Append
"SEALED_DEV_USED: False"|Out-File $report -Append
if($xg.MainWindowTitle -notlike '*Position.xgp*'){Snap 'reach-dynamic-title-mismatch';throw 'Dynamic XGID did not load as Position.xgp'}
Get-Content $report
'@

$ps1=Join-Path $env:RUNNER_TEMP 'xg-reach-dynamic-v20-generated.ps1'
Set-Content $ps1 ($prefix+$tail) -Encoding UTF8
& $ps1
