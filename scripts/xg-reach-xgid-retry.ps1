$ErrorActionPreference='Stop'
$maxAttempts=2
$lastError=$null
for($attempt=1;$attempt-le$maxAttempts;$attempt++){
  try{
    Write-Host "XG startup attempt $attempt of $maxAttempts"
    & "$env:GITHUB_WORKSPACE\scripts\xg-reach-xgid.ps1"
    Write-Host "XG startup attempt $attempt succeeded"
    exit 0
  }catch{
    $lastError=$_
    Write-Warning "XG startup attempt $attempt failed: $($_.Exception.Message)"
    if($attempt-ge$maxAttempts){break}
    Get-Process eXtremeGammon2,test3d -ErrorAction SilentlyContinue|Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 3
  }
}
throw "XG startup failed after $maxAttempts attempts: $($lastError.Exception.Message)"
