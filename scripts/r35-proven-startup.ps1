$ErrorActionPreference='Stop'

$yaml=Get-Content "$env:GITHUB_WORKSPACE\.github\workflows\xg-analyze-level-public-v1.yml" -Raw
$m=[regex]::Match($yaml,'(?ms)^      - name: Run proven startup and capture Analyze Level\r?\n        shell: powershell\r?\n        run: \|\r?\n(?<script>.*?)(?=^      - name: Upload evidence)')
if(-not$m.Success){throw 'Could not extract proven XG startup'}
$script=$m.Groups['script'].Value -replace '(?m)^          ',''
$marker="'XGID_POSITION_READY: True'|Out-File `$report -Append"
$idx=$script.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'XGID_POSITION_READY marker missing'}
$prefix=$script.Substring(0,$idx+$marker.Length)
$prefix=$prefix.Replace("$env:GITHUB_WORKSPACE\\xg-public-v1-report.txt","$env:GITHUB_WORKSPACE\\r35-proven-startup-report.txt")
$ps1=Join-Path $env:RUNNER_TEMP 'r35-proven-startup-generated.ps1'
Set-Content $ps1 $prefix -Encoding UTF8
& $ps1
$xg=Get-Process eXtremeGammon2 -ErrorAction Stop | Select-Object -First 1
$xg.Refresh()
if($xg.HasExited){throw 'XG exited after proven startup'}
"R35_PROVEN_STARTUP=PASS PID=$($xg.Id) HWND=$($xg.MainWindowHandle)"|Tee-Object -FilePath "$env:GITHUB_WORKSPACE\r35-proven-startup-summary.txt"
