$ErrorActionPreference='Stop'

$yaml=Get-Content "$env:GITHUB_WORKSPACE\.github\workflows\xg-analyze-level-public-v1.yml" -Raw
$m=[regex]::Match($yaml,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not$m.Success){throw 'Could not extract public v1 proven startup'}
$script=$m.Groups['script'].Value -replace '(?m)^          ',''
$script=$script.Replace('xg-public-v1-report.txt','xg-reach-xgid-report.txt').Replace('XG public Analyze Level v1','XG reach XGID')

$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$script.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v1 XGID_POSITION_READY marker missing'}
$prefix=$script.Substring(0,$idx+$marker.Length)
$tail=@'

$xg.Refresh()
"XG_RESPONDING_AT_XGID: $($xg.Responding)"|Out-File $report -Append
"XG_TITLE_AT_XGID: $($xg.MainWindowTitle)"|Out-File $report -Append
if($xg.MainWindowTitle -notlike '*Position.xgp*'){Snap 'reach-xgid-title-mismatch';throw 'Known XGID did not load as Position.xgp'}
Get-Content $report
'@
$ps1=Join-Path $env:RUNNER_TEMP 'xg-reach-xgid-generated.ps1'
Set-Content $ps1 ($prefix+$tail) -Encoding UTF8
& $ps1
