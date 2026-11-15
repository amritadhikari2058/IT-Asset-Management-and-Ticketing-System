# Backup and Restore Runbook

This document describes the backup and restore procedure for the IT Ticketing
and Asset Management System. It covers the database, uploaded media, and
configuration.

**Never run destructive backup or restore operations against the existing
development database without an explicit, verified copy.**

## What to back up

| Component | Location | Notes |
|-----------|----------|-------|
| Database | `backend/db.sqlite3` (dev) / PostgreSQL (prod) | All application data |
| Uploaded media | `backend/media/` (dev) / S3 bucket (prod) | Attachments, employee photos |
| Configuration | `.env` (repo root) | Environment variables — never commit |
| Migrations | `*/migrations/` | Schema history — version-controlled |

## Database backup

### Development (SQLite)

The dev database is a single file. Stop the Django process (or use a
consistent snapshot), then copy the file:

```bash
cp backend/db.sqlite3 backups/db-$(date +%F).sqlite3
```

SQLite supports online backup while running, but for simplicity and
consistency, copy while the app is stopped or use a filesystem snapshot.

### Production (PostgreSQL)

Use `pg_dump` (logical, portable) or `pg_basebackup` (physical). Recommended:

```bash
# Logical dump — portable across PG versions, includes schema + data
pg_dump -h $PGHOST -U $PGUSER $PGDATABASE \
  > backups/db-$(date +%F).sql

# Compressed
pg_dump ... | gzip > backups/db-$(date +%F).sql.gz
```

`pg_dump` is non-blocking and safe to run against a live production
database.

## Media backup

### Development (local filesystem)

```bash
tar czf backups/media-$(date +%F).tar.gz -C backend media
```

### Production (S3-compatible object storage)

Media is stored in the configured S3 bucket (`AWS_STORAGE_BUCKET_NAME`).
Back up the bucket using your provider's tools:

- **AWS S3**: `aws s3 sync s3://$BUCKET backups/media-$(date +%F)/` or
  S3 Batch Operations / cross-region replication.
- **S3-compatible (MinIO, etc.)**: Use `mc mirror` or the provider's
  equivalent.

Files are private (no public URLs). The bucket itself is the source of
truth; application code only references stored names.

## Configuration backup

Back up `.env` (or your production secret store) — it holds `SECRET_KEY`,
SMTP credentials, S3 settings, and allowed hosts. Store it in a secrets
manager (e.g. AWS Secrets Manager, HashiCorp Vault), never in Git.

## Backup scheduling (recommendations)

| Component | Frequency | Retention |
|-----------|-----------|-----------|
| Database (pg_dump) | Daily, off-peak | 30 days daily, 12 weekly, 6 monthly |
| Media | Weekly (or continuous via replication) | 30 days |
| Configuration (.env / secrets) | On change | Indefinite (versioned secret store) |

Automate with cron, your orchestrator's scheduled jobs, or your cloud
provider's backup service. Test restores quarterly.

## Restoration instructions

### Database — development (SQLite)

```bash
# 1. Stop the application
# 2. Replace the database file
cp backups/db-YYYY-MM-DD.sqlite3 backend/db.sqlite3
# 3. Run migrations to ensure schema is current
cd backend
python manage.py migrate
# 4. Restart the application
```

### Database — production (PostgreSQL)

```bash
# 1. Put the app in maintenance mode (stop workers/web)
# 2. Restore the dump
pg_dump -h $PGHOST -U $PGUSER $PGDATABASE < backups/db-YYYY-MM-DD.sql
#    (or: psql ... < backups/db-YYYY-MM-DD.sql)
# 3. Run migrations
cd backend
python manage.py migrate
# 4. Restart web + Celery worker + beat
```

### Media — development

```bash
tar xzf backups/media-YYYY-MM-DD.tar.gz -C backend
```

### Media — production (S3)

Sync back to the bucket:

```bash
aws s3 sync backups/media-YYYY-MM-DD/ s3://$BUCKET --delete
```

## Verification

A backup is only useful if it can be restored. Verify each backup:

1. **Database**: Restore to a throwaway instance, run `python manage.py
   check`, and confirm a sample of records (users, tickets, assets) are
   present and readable.
2. **Media**: Confirm a sample attachment downloads through the
   permission-checked `/api/.../attachments/<id>/download/` endpoint after
   restore.
3. **Configuration**: Confirm `SECRET_KEY` and SMTP/S3 variables load
   correctly and the app boots.

Record the result of each test restore (date, operator, outcome).

## Retention policy

- Daily database dumps: 30 days
- Weekly database dumps: 12 weeks
- Monthly database dumps: 6 months
- Media: 30 days (mirroring the bucket via continuous replication is
  preferred over point-in-time tarballs)

Adjust based on your organization's regulatory requirements.

## What NOT to do

- Do not run `pg_dump`/`pg_restore` or SQLite file replacement against the
  live development database without a verified copy.
- Do not store `.env` or database credentials in Git.
- Do not rely solely on soft-deleted rows as "backup" — soft deletion is an
  operational undo mechanism, not disaster recovery.

## Phase 27 — Automated backup app (`backup`)

In addition to the manual runbook above, the system ships a `backup` Django
app (`/api/backup/...`) that automates database, media and full backups,
verification, retention, and controlled restore.

### What it covers
- **Database backups**: SQLite via `sqlite3.Connection.backup()` (online
  backup API, WAL-aware, consistent snapshot) or `pg_dump \| gzip` for
  PostgreSQL (when `pg_dump`/`gzip` are on PATH).
- **Media backups**: `tar.gz` of `MEDIA_ROOT`; empty media yields a
  verifiable empty tarball.
- **Full backups**: database + media; recoverable only when both complete.
- **Verification**: SHA-256 recomputed after the artifact is fully written;
  artifact existence, readability and checksum match are confirmed.
- **Scheduling**: `BackupSchedule` rows drive Celery Beat entries via
  `backup.tasks.sync_beat_schedules` (Phase 26 beat entries are never
  clobbered).
- **Retention**: `BackupRetentionPolicy` + per-schedule `retention_days` /
  `keep_min_count`; the only recoverable backup of a type is never deleted,
  and artifacts referenced by a pending/running restore are protected.
- **Restore (controlled)**: System Admin only, explicit `confirm=true`, no
  concurrent restores. SQLite restores create a verified pre-restore
  checkpoint, restore into a temp file first, validate, replace the live DB
  atomically, run `migrate --noinput`, and recover automatically from the
  checkpoint if replacement or post-replacement validation fails.
- **PostgreSQL restore**: NOT automated; a clear documented limitation is
  returned instead of attempting a destructive live restore (`pg_restore`
  requires DBA-assisted connection termination).
- **Monitoring**: failures raise `common.OperationalAlert` records (component
  `database`/`storage`) via `common.monitoring_service.create_or_update_alert`;
  outcomes and correlation IDs are recorded in
  `common.BackgroundTaskRun`. The removed `operations` app is not used.

### Artifact storage
Backups live under `BACKUP_ROOT` (default: `backend/backups/`), separate from
user uploads (`MEDIA_ROOT`). Only metadata + checksums are returned through
the API — no filesystem paths or credentials. Protect `BACKUP_ROOT` with OS
permissions; artifacts are not encrypted at rest by the application.

### Endpoints
- `GET|POST /api/backup/backups/` — list / create (on-demand) backups
- `POST /api/backup/backups/<id>/verify/` — verify an artifact
- `POST /api/backup/backups/run-retention/` — run retention cleanup
- `GET|POST /api/backup/restores/` — list / initiate restores
- `GET|POST|PATCH|PUT|DELETE /api/backup/schedules/` — schedules
- `GET|POST|PATCH|PUT|DELETE /api/backup/retention/` — retention policies
- `GET /api/backup/readiness/` — recovery readiness snapshot

Permissions: IT staff may view; System Admin may create/verify backups,
manage schedules, configure retention, and initiate restores. Restore requires
`confirm: true` and is blocked while another restore is in progress. All
permissions are enforced in the backend.

### Known limitations
- PostgreSQL live restore is not automated (DBA-assisted; documented).
- Backup artifacts are not encrypted at rest by the application.
- Distributed backup locking requires a shared cache backend (Redis);
  LocMem is per-process only.
- No production backup/restore has been executed against a live
  PostgreSQL/Redis/S3 deployment; validate before relying on this in
  production.
