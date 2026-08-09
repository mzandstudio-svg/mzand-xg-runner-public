$ErrorActionPreference='Stop'
$src=Get-Content "$env:GITHUB_WORKSPACE\scripts\xg-run-position-analysis-v8.ps1" -Raw
$marker='Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue'
$idx=$src.IndexOf($marker,[System.StringComparison]::Ordinal)
if($idx-lt0){throw 'v8 cleanup marker missing'}
$prefix=$src.Substring(0,$idx)
$tail=@'

$xg.Refresh()
[N]::SetForegroundWindow([IntPtr]$xg.MainWindowHandle)|Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('^c')
Start-Sleep 1
$text=''
try{$text=Get-Clipboard -Raw -TextFormatType Text}catch{$text=Get-Clipboard -Raw}
if($null-eq$text){$text=''}
Set-Content "$env:GITHUB_WORKSPACE\xg-v13-position-clipboard.txt" $text -Encoding UTF8
"CLIPBOARD_LENGTH: $($text.Length)"|Out-File "$env:GITHUB_WORKSPACE\xg-v13-report.txt"
"CLIPBOARD_HAS_XGID: $($text -match 'XGID=')"|Out-File "$env:GITHUB_WORKSPACE\xg-v13-report.txt" -Append
"CLIPBOARD_HAS_EQ: $($text -match 'eq:|Equity|\+0\.|-0\.')"|Out-File "$env:GITHUB_WORKSPACE\xg-v13-report.txt" -Append
"CLIPBOARD_HAS_PLAYER: $($text -match 'Player')"|Out-File "$env:GITHUB_WORKSPACE\xg-v13-report.txt" -Append
"CLIPBOARD_HAS_MOVE_24_23: $($text -match '24/23')"|Out-File "$env:GITHUB_WORKSPACE\xg-v13-report.txt" -Append
'POSITION_TO_CLIPBOARD_DEFAULT_SENT: True'|Out-File "$env:GITHUB_WORKSPACE\xg-v13-report.txt" -Append
Post 'xg-public-v13/clipboard-exported' $(if($text.Length-gt0){'success'}else{'failure'}) "default position clipboard length=$($text.Length)"
Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
'@
$generated=Join-Path $env:RUNNER_TEMP 'xg-v13-generated.ps1'
Set-Content $generated ($prefix+$tail) -Encoding UTF8
& $generated
