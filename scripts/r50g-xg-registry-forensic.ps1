$ErrorActionPreference='Continue'
$root='HKCU\Software\GameSite 2000\eXtreme Gammon 2'
$out=Join-Path $env:GITHUB_WORKSPACE 'r50g-xg-registry.txt'
$reg=Join-Path $env:GITHUB_WORKSPACE 'r50g-xg-registry.reg'
"R50G_BEGIN" | Out-File $out -Encoding utf8
"R50G_ROOT=$root" | Out-File $out -Append -Encoding utf8
reg query $root /s 2>&1 | Out-File $out -Append -Encoding utf8
reg export $root $reg /y 2>&1 | Out-File $out -Append -Encoding utf8
"R50G_ANALZYE_QUERY" | Out-File $out -Append -Encoding utf8
reg query "$root\Analzye" /s 2>&1 | Out-File $out -Append -Encoding utf8
"R50G_ANALYZE_TEXT_HITS" | Out-File $out -Append -Encoding utf8
Get-Content $out | Select-String -Pattern 'Analzye|Analyze|Very Quick|Fast|Deep|Thorough|World Class|Extensive|Custom|ply' -CaseSensitive:$false | ForEach-Object { $_.Line } | Out-File $out -Append -Encoding utf8
"R50G_REGISTRY_CAPTURE=PASS" | Out-File $out -Append -Encoding utf8
Get-Content $out
