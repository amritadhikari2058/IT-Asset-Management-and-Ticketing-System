#Requires -Version 5.1
<#
.SYNOPSIS
    Safe, non-destructive SQLite backup + integrity verification for the
    IT Ticketing & Asset Management System development database.

.DESCRIPTION
    Creates a consistent copy of backend/db.sqlite3 using SQLite's online
    backup API (via a short Python helper), never by blindly copying the file
    while writes may be in flight. Each backup gets a timestamped filename,
    a SHA-256 checksum, and a recorded file size. Existing backups are never
    overwritten silently.

    The script also verifies integrity by running `PRAGMA integrity_check`
    against a temporary copy and deleting only that temporary artifact.

    Safety rules:
      - Never deletes or overwrites backend/db.sqlite3.
      - Never restores over the live development database.
      - Never includes secrets.
      - Only touches the temporary verification copy it creates.
      - Media is backed up separately (optionally) as a tarball.

.PARAMETER Destination
    Backup directory (default: backups under the repo root).

.PARAMETER DbPath
    Path to the SQLite database (default: backend/db.sqlite3).

.PARAMETER MediaPath
    Path to the media directory (default: backend/media).

.PARAMETER WithMedia
    Also back up the media directory.

.PARAMETER Python
    Python executable (default: python).

.EXAMPLE
    .\scripts\backup_verify_sqlite.ps1 -Destination .\backups -WithMedia

.NOTES
    Restore must NEVER be run over the active development database. Restore
    to an isolated copy and verify there first.
#>
param(
    [string]$Destination = "backups",
    [string]$DbPath = "backend\db.sqlite3",
    [string]$MediaPath = "backend\media",
    [switch]$WithMedia,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$script:errors = @()

function Write-Result([string]$status, [string]$check, [string]$message, [string]$remediation = "") {
    $pad = " " * [Math]::Max(0, 44 - $check.Length)
    $rem = if ($remediation) { "  -> $remediation" } else { "" }
    Write-Host "$status  $check$pad$message$rem"
    if ($status -eq "ERROR") { $script:errors += $check }
}

# Resolve paths relative to the repo root (this script's parent).
$repoRoot = (Get-Item (Join-Path $PSScriptRoot "..")).FullName
$dest = Join-Path $repoRoot $Destination
$dbFull = Join-Path $repoRoot $DbPath
$mediaFull = Join-Path $repoRoot $MediaPath

if (-not (Test-Path $dbFull)) {
    Write-Result "ERROR" "sqlite.db_missing" "Database not found: $dbFull" "Check DbPath."
    exit 1
}

New-Item -ItemType Directory -Path $dest -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupName = "db-$timestamp.sqlite3"
$backupPath = Join-Path $dest $backupName

# Never overwrite an existing backup silently.
if (Test-Path $backupPath) {
    Write-Result "ERROR" "sqlite.backup_exists" "Backup already exists: $backupPath" "Use a different destination or wait."
    exit 1
}

# ---- 1. Consistent SQLite backup via the online backup API -------------
# Python helper opens the source and uses sqlite3.backup to a destination
# file. This produces a transactionally consistent snapshot without locking
# the source for long.
$backupPython = @"
import sqlite3, sys, os
src = os.environ["SQLITE_SRC"]
dst = os.environ["SQLITE_DST"]
if os.path.abspath(src) == os.path.abspath(dst):
    print("ERROR: source and destination are the same file"); sys.exit(1)
con = sqlite3.connect(src)
bkp = sqlite3.connect(dst)
with bkp:
    con.backup(bkp)
bkp.close(); con.close()
print("OK")
"@

$env:SQLITE_SRC = $dbFull
$env:SQLITE_DST = $backupPath
$backupOut = & $Python -c $backupPython 2>&1
if ($backupOut -notmatch "OK") {
    Write-Result "ERROR" "sqlite.backup_failed" "SQLite backup failed: $backupOut"
    exit 1
}
Write-Result "PASS" "sqlite.backup" "Database backed up to $backupName"

# ---- 2. Checksum + size ------------------------------------------------
$hash = Get-FileHash -Path $backupPath -Algorithm SHA256
$size = (Get-Item $backupPath).Length
$checksumPath = "$backupPath.sha256"
$sizePath = "$backupPath.size"
$hash.Hash | Out-File -FilePath $checksumPath -Encoding ascii
$size | Out-File -FilePath $sizePath -Encoding ascii
Write-Result "PASS" "sqlite.checksum" "SHA-256: $($hash.Hash)"
Write-Result "PASS" "sqlite.size" "Size: $size bytes"

# ---- 3. Integrity verification on a TEMPORARY copy -------------------
# Copy the backup to a temp path, run integrity_check, delete only the temp.
$tempDb = Join-Path $env:TEMP "sqlite_verify_$timestamp.sqlite3"
Copy-Item -Path $backupPath -Destination $tempDb -Force

$verifyPython = @"
import sqlite3, sys
con = sqlite3.connect(os.environ["SQLITE_TMP"])
cur = con.execute("PRAGMA integrity_check")
row = cur.fetchone()
con.close()
print(row[0] if row else "unknown")
"@
$env:SQLITE_TMP = $tempDb
$integrityOut = & $Python -c $verifyPython 2>&1
if ($integrityOut -eq "ok") {
    Write-Result "PASS" "sqlite.integrity" "PRAGMA integrity_check: ok"
} else {
    Write-Result "ERROR" "sqlite.integrity" "integrity_check returned: $integrityOut"
}
# Delete only the temporary artifact we created.
if (Test-Path $tempDb) { Remove-Item -Path $tempDb -Force }

# ---- 4. Optional media backup ------------------------------------------
if ($WithMedia) {
    if (Test-Path $mediaFull) {
        $mediaName = "media-$timestamp.tar.gz"
        $mediaPath = Join-Path $dest $mediaName
        if (Test-Path $mediaPath) {
            Write-Result "WARNING" "media.backup_exists" "Media backup already exists: $mediaName"
        } else {
            & tar -czf $mediaPath -C $repoRoot media 2>&1 | Out-Null
            if (Test-Path $mediaPath) {
                $mhash = Get-FileHash -Path $mediaPath -Algorithm SHA256
                $msize = (Get-Item $mediaPath).Length
                Write-Result "PASS" "media.backup" "Media backed up: $mediaName ($msize bytes)"
                Write-Result "PASS" "media.checksum" "SHA-256: $($mhash.Hash)"
            } else {
                Write-Result "ERROR" "media.backup_failed" "Media tarball was not created."
            }
        }
    } else {
        Write-Result "WARNING" "media.missing" "Media directory not found: $mediaFull"
    }
}

# ---- Summary -----------------------------------------------------------
Write-Host ""
Write-Host "=== Backup summary ==="
Write-Result "INFO" "sqlite.backup_path" $backupPath
Write-Result "INFO" "sqlite.errors" "$($script:errors.Count) error(s)"

if ($script:errors.Count -gt 0) {
    Write-Host ""
    Write-Host "BACKUP FAILED: $($script:errors.Count) error(s) recorded." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "BACKUP COMPLETE: database backup + checksum + integrity verified." -ForegroundColor Green
Write-Host "Restore warning: never restore over the live development database."
exit 0
