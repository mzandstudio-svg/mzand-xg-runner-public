param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$install=Split-Path -Parent $ExePath
$report=Join-Path $OutDir 'xg-assets-inventory.tsv'
"category`trelative_path`tsize`tsha256" | Out-File $report -Encoding utf8

$patterns=@(
  @{Category='MET'; Pattern='*.met'},
  @{Category='MODEL'; Pattern='*.dat'},
  @{Category='OPENING_BOOK'; Pattern='*.ob'},
  @{Category='DATABASE'; Pattern='*.db'},
  @{Category='DATABASE'; Pattern='*.bd'},
  @{Category='LIBRARY'; Pattern='*.dll'},
  @{Category='HELP'; Pattern='*.chm'},
  @{Category='CONFIG'; Pattern='*.ini'},
  @{Category='CONFIG'; Pattern='*.xml'}
)

$seen=New-Object 'System.Collections.Generic.HashSet[string]'
foreach($spec in $patterns){
  Get-ChildItem $install -Recurse -File -Filter $spec.Pattern -ErrorAction SilentlyContinue | ForEach-Object {
    $full=$_.FullName
    if($seen.Add($full)){
      $rel=$full.Substring($install.Length).TrimStart('\')
      $sha=(Get-FileHash $full -Algorithm SHA256).Hash.ToLowerInvariant()
      "$($spec.Category)`t$rel`t$($_.Length)`t$sha" | Out-File $report -Append -Encoding utf8
    }
  }
}

# Separate MET metadata dump without modifying source files.
$metMeta=Join-Path $OutDir 'met-metadata.tsv'
"relative_path`tname`tversion`tdescription`tpre_size`tpost_size`tsha256" | Out-File $metMeta -Encoding utf8
Get-ChildItem $install -Recurse -File -Filter *.met -ErrorAction SilentlyContinue | ForEach-Object {
  $txt=Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
  $name='';$version='';$desc='';$pre='';$post=''
  if($txt-match'(?mi)^Name=(.*)$'){$name=$Matches[1].Trim()}
  if($txt-match'(?mi)^Version=(.*)$'){$version=$Matches[1].Trim()}
  if($txt-match'(?mi)^Description=(.*)$'){$desc=$Matches[1].Trim()}
  if($txt-match'(?ms)\[PreCrawford\].*?^Size=(\d+)'){$pre=$Matches[1]}
  if($txt-match'(?ms)\[PostCrawford\].*?^Size=(\d+)'){$post=$Matches[1]}
  $rel=$_.FullName.Substring($install.Length).TrimStart('\')
  $sha=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  "$rel`t$name`t$version`t$desc`t$pre`t$post`t$sha" | Out-File $metMeta -Append -Encoding utf8
}

# Record executable version so we can compare user's package with the currently served official installer.
$vi=(Get-Item $ExePath).VersionInfo
@(
  "exe=$ExePath",
  "file_version=$($vi.FileVersion)",
  "product_version=$($vi.ProductVersion)",
  "sha256=$((Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant())"
) | Out-File (Join-Path $OutDir 'executable-version.txt') -Encoding utf8

Write-Host "Inventory written to $OutDir"
