$lines = Get-Content "backend/monitoring/urls.py"
$fixed = @()
foreach ($line in $lines) {
    if ($line -match "target_coverage\",$") {
        $line = $line -replace "target_coverage\",$", "target_coverage"),"
    }
    $fixed += $line
}
$fixed | Set-Content "backend/monitoring/urls.py"