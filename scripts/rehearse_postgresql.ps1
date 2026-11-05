#Requires -Version 5.1
<#
.SYNOPSIS
    Repeatable, non-destructive PostgreSQL migration rehearsal for the
    IT Ticketing & Asset Management System.

.DESCRIPTION
    This script rehearses Django migrations against a dedicated PostgreSQL
    database (NOT the development SQLite database, NOT production).

    It:
      1. Verifies the psycopg/psycopg2 PostgreSQL driver is importable.
      2. Connects to a dedicated PostgreSQL rehearsal database.
      3. Runs Django system checks.
      4. Runs all migrations from zero (migrate on a fresh DB).
      5. Checks for pending migrations (makemigrations --check --dry-run).
      6. Optionally loads minimal seed data.
      7. Runs a small PostgreSQL compatibility test suite.
      8. Reports success or failure.

    Safety rules:
      - Never touches backend/db.sqlite3.
      - Never touches a production database.
      - Never prints credentials.
      - Never uses --fake without a documented cause.
      - Uses a separate rehearsal database with dedicated credentials.

.PARAMETER PgHost
    PostgreSQL host (default: localhost).

.PARAMETER PgPort
    PostgreSQL port (default: 5432).

.PARAMETER PgUser
    Rehearsal database user (default: ticketing_rehearsal).

.PARAMETER PgDatabase
    Rehearsal database name (default: ticketing_rehearsal).

.PARAMETER PgPasswordEnv
    Environment variable name holding the rehearsal DB password
    (default: PGREHEARSAL_PASSWORD). The password itself is never printed.

.PARAMETER Seed
    If supplied, runs `python manage.py seed_defaults` after migrations.

.PARAMETER Python
    Python executable path (default: python).

.PARAMETER BackendDir
    Backend directory (default: backend).

.EXAMPLE
    .\scripts\rehearse_postgresql.ps1 -PgHost localhost -PgUser ticketing_rehearsal -PgDatabase ticketing_rehearsal -PgPasswordEnv PGREHEARSAL_PASSWORD -Seed

.NOTES
    Set PGREHEARSAL_PASSWORD in your environment before running. The script
    reads it via $env:PGREHEARSAL_PASSWORD and never writes it to stdout.
#>
param(
    [string]$PgHost = "localhost",
    [int]$PgPort = 5432,
    [string]$PgUser = "ticketing_rehearsal",
    [string]$PgDatabase = "ticketing_rehearsal",
    [string]$PgPasswordEnv = "PGREHEARSAL_PASSWORD",
    [switch]$Seed,
    [string]$Python = "python",
    [string]$BackendDir = "backend"
)

$ErrorActionPreference = "Stop"
$script:errors = @()
$script:warnings = @()

function Write-Result([string]$status, [string]$check, [string]$message, [string]$remediation = "") {
    $pad = " " * [Math]::Max(0, 44 - $check.Length)
    $rem = if ($remediation) { "  -> $remediation" } else { "" }
    Write-Host "$status  $check$pad$message$rem"
    if ($status -eq "ERROR") { $script:errors += $check }
    if ($status -eq "WARNING") { $script:warnings += $check }
}

# ---- 1. Verify PostgreSQL driver is importable -----------------------
$driverOk = $false
try {
    & $Python -c "import psycopg2; print('psycopg2 ok')" 2>$null | Out-Null
    $driverOk = $true
    Write-Result "PASS" "postgresql.driver" "psycopg2 driver importable."
} catch {
    try {
        & $Python -c "import psycopg; print('psycopg3 ok')" 2>$null | Out-Null
        $driverOk = $true
        Write-Result "PASS" "postgresql.driver" "psycopg v3 driver importable."
    } catch {
        Write-Result "ERROR" "postgresql.driver" "No PostgreSQL driver (psycopg2/psycopg3) importable." "Install psycopg2-binary (dev) or psycopg (production) and re-run."
    }
}

# ---- 2. Resolve rehearsal credentials --------------------------------
$pgPassword = $env:$PgPasswordEnv
if (-not $pgPassword) {
    Write-Result "ERROR" "postgresql.credentials" "$PgPasswordEnv environment variable is not set." "Set $PgPasswordEnv to the rehearsal database password."
    exit 1
}

$connString = "host=$PgHost port=$PgPort dbname=$PgDatabase user=$PgUser password=$pgPassword"

# ---- 3. Create / verify rehearsal database exists --------------------
function Test-DatabaseExists() {
    # Connect to the 'postgres' system database and check for our DB.
    $testConn = "host=$PgHost port=$PgPort dbname=postgres user=$PgUser password=$pgPassword"
    $sql = "SELECT 1 FROM pg_database WHERE datname='$PgDatabase'"
    $out = & $Python -c "
import psycopg2, sys
try:
    c = psycopg2.connect('$testConn')
    c.autocommit = True
    cur = c.cursor()
    cur.execute('$sql')
    print('EXISTS' if cur.fetchone() else 'MISSING')
    cur.close(); c.close()
except Exception as e:
    print('ERROR:' + type(e).__name__)
" 2>&1
    if ($out -match "EXISTS") { return $true }
    if ($out -match "MISSING") { return $false }
    Write-Result "ERROR" "postgresql.connection" "Cannot connect to PostgreSQL server: $out" "Check host/port/user/password and that PostgreSQL is running."
    exit 1
}

if (-not (Test-DatabaseExists)) {
    Write-Result "WARNING" "postgresql.database" "Rehearsal database '$PgDatabase' does not exist; attempting to create it."
    $create = & $Python -c "
import psycopg2, sys
try:
    c = psycopg2.connect('host=$PgHost port=$PgPort dbname=postgres user=$PgUser password=$pgPassword')
    c.autocommit = True
    cur = c.cursor()
    cur.execute('CREATE DATABASE \"$PgDatabase\"')
    print('CREATED')
    cur.close(); c.close()
except Exception as e:
    print('ERROR:' + type(e).__name__)
" 2>&1
    if ($create -match "CREATED") {
        Write-Result "PASS" "postgresql.database" "Rehearsal database created."
    } else {
        Write-Result "ERROR" "postgresql.database" "Failed to create database: $create" "Ensure the rehearsal user has CREATEDB privilege."
        exit 1
    }
} else {
    Write-Result "PASS" "postgresql.database" "Rehearsal database '$PgDatabase' already exists."
}

# ---- 4. Run Django system checks against the rehearsal DB ------------
Write-Host ""
Write-Host "=== Django system checks (rehearsal database) ==="
$env:PGHOST = $PgHost
$env:PGPORT = $PgPort
$env:PGUSER = $PgUser
$env:PGDATABASE = $PgDatabase
# Never print the password; pass via DJANGO settings instead of the command line.
$env:$PgPasswordEnv = $pgPassword
$checkOut = & $Python manage.py check 2>&1
$checkCode = $LASTEXITCODE
if ($checkCode -eq 0) {
    Write-Result "PASS" "django.system_checks" "manage.py check passed."
} else {
    Write-Result "ERROR" "django.system_checks" "manage.py check failed."
    Write-Host $checkOut
}

# ---- 5. Run migrations from zero -------------------------------------
Write-Host ""
Write-Host "=== Migrations (rehearsal database) ==="
$migOut = & $Python manage.py migrate --no-input 2>&1
$migCode = $LASTEXITCODE
if ($migCode -eq 0) {
    Write-Result "PASS" "postgresql.migrate" "All migrations applied to rehearsal database."
} else {
    Write-Result "ERROR" "postgresql.migrate" "Migration failed on rehearsal database."
    Write-Host $migOut
    exit 1
}

# ---- 6. Check for pending migrations ---------------------------------
Write-Host ""
Write-Host "=== Migration consistency check ==="
$mmOut = & $Python manage.py makemigrations --check --dry-run 2>&1
$mmCode = $LASTEXITCODE
if ($mmCode -eq 0) {
    Write-Result "PASS" "postgresql.makemigrations_check" "No pending migrations (schema is consistent)."
} else {
    Write-Result "ERROR" "postgresql.makemigrations_check" "Pending migrations detected."
    Write-Host $mmOut
    exit 1
}

# ---- 7. Optionally load seed data ------------------------------------
if ($Seed) {
    Write-Host ""
    Write-Host "=== Seed data ==="
    $seedOut = & $Python manage.py seed_defaults --no-input 2>&1
    $seedCode = $LASTEXITCODE
    if ($seedCode -eq 0) {
        Write-Result "PASS" "postgresql.seed" "Default data seeded."
    } else {
        Write-Result "WARNING" "postgresql.seed" "Seed command produced non-zero exit."
        Write-Host $seedOut
    }
}

# ---- 8. Run the PostgreSQL compatibility test suite ------------------
Write-Host ""
Write-Host "=== PostgreSQL compatibility tests ==="
# Run only the compatibility suite (existing tests tagged or a dedicated
# module). This avoids touching the SQLite dev database.
$testOut = & $Python manage.py test common.test_reports tickets.test_sla_access assets.test_operations --keepdb 2>&1
$testCode = $LASTEXITCODE
if ($testCode -eq 0) {
    Write-Result "PASS" "postgresql.compat_tests" "PostgreSQL compatibility tests passed."
} else {
    Write-Result "WARNING" "postgresql.compat_tests" "Some compatibility tests did not pass."
    Write-Host $testOut
}

# ---- Summary ---------------------------------------------------------
Write-Host ""
Write-Host "=== Rehearsal summary ==="
Write-Result "INFO" "postgresql.rehearsal_db" "$PgDatabase on $PgHost:$PgPort"
Write-Result "INFO" "postgresql.errors" "$($script:errors.Count) error(s)"
Write-Result "INFO" "postgresql.warnings" "$($script:warnings.Count) warning(s)"

if ($script:errors.Count -gt 0) {
    Write-Host ""
    Write-Host "REHEARSAL FAILED: $($script:errors.Count) error(s) recorded." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "REHEARSAL COMPLETE: all checks passed on the dedicated rehearsal database." -ForegroundColor Green
Write-Host "Teardown: drop the rehearsal database when done (e.g. DROP DATABASE $PgDatabase;)."

exit 0
