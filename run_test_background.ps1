$runDir = "$env:TEMP\monitoring_policy_single_test"
$stdout = "$runDir\future_effective.stdout.log"
$stderr = "$runDir\future_effective.stderr.log"
$exitFile = "$runDir\future_effective.exit.txt"
$pidFile = "$runDir\future_effective.pid.txt"
$startFile = "$runDir\future_effective.start.txt"

# Remove only stale diagnostic files belonging to this exact task
Remove-Item $stdout,$stderr,$exitFile,$pidFile,$startFile -Force -ErrorAction SilentlyContinue

# Create directory if it doesn't exist
if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
}

# Write start time
$started = Get-Date
$started.ToString("o") | Set-Content -Encoding UTF8 $startFile

# Run the Django test as a background process with redirected logs
$command = @"
$started = Get-Date
$started.ToString(""o"") | Set-Content -Encoding UTF8 "$env:TEMP\monitoring_policy_single_test\future_effective.start.txt"
& python backend/manage.py test monitoring.test_ticket_automation.PolicyTestCase.test_policy_before_effective_date_fails_closed --verbosity 3 --keepdb --noinput 1> "$env:TEMP\monitoring_policy_single_test\future_effective.stdout.log" 2> "$env:TEMP\monitoring_policy_single_test\future_effective.stderr.log"
$LASTEXITCODE | Set-Content -Encoding ASCII "$env:TEMP\monitoring_policy_single_test\future_effective.exit.txt"
"@

$process = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile","-Command",$command -WorkingDirectory "D:\IT-Asset-Management-and-Ticketing-System" -PassThru -WindowStyle Hidden
$process.Id | Set-Content -Encoding ASCII $pidFile

Write-Output "STARTED_PID=$($process.Id)"