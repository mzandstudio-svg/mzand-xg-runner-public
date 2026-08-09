$ErrorActionPreference='Stop'
if(-not$env:POSITION_XGID){throw 'POSITION_XGID is required'}
$target=$env:POSITION_XGID.Trim()
if($target-notlike'XGID=*'){throw 'POSITION_XGID must start with XGID='}

$srcPath=Join-Path $env:GITHUB_WORKSPACE 'scripts\xg-parallel-candidate-xgrpp-v21.ps1'
$src=Get-Content $srcPath -Raw
$old=@'
$expectedPayload='-a---BDBBA--dBb--c-dBa----:1:-1:-1:64:6:16:0:19:10'
'@
$old=$old.Trim()
$new='$expectedPayload=$env:POSITION_XGID.Substring(5)'
if(-not$src.Contains($old)){throw 'v21 expected payload marker not found'}
$generated=$src.Replace($old,$new)
$tmp=Join-Path $env:RUNNER_TEMP "xg-v25-xgrpp-candidate-$env:CANDIDATE_RANK.ps1"
Set-Content $tmp $generated -Encoding UTF8
& $tmp
