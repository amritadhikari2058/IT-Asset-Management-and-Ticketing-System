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
