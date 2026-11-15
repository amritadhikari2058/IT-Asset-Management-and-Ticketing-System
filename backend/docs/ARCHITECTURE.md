# System Architecture

## Overview

The IT Ticketing and Asset Management System is a monolithic Django 6 +
Django REST Framework backend with a React (Vite) frontend. It is designed
for a single organizational deployment with role-based access control
(System Admin, IT Manager, IT Support, Employee).

## Components

| Component | Technology | Responsibility |
|-----------|-----------|----------------|
| Backend API | Django 6 + DRF | Business logic, auth, permissions, serialization |
| Frontend | React + Vite | SPA consumed via the REST API |
| Database | PostgreSQL (prod) / SQLite (dev) | Application data, soft-delete, triggers |
| Cache / broker | Redis 7 | Celery broker, result backend, Django cache |
| Background jobs | Celery worker + beat | SLA escalations, maintenance reminders, email intake |
| Object storage | S3-compatible (prod) / local (dev) | Private attachments, employee photos |
| Backup / DR | `backup` app (SQLite online API, `pg_dump\|gzip`, tar media) | Database/media/full backups, SHA-256 verification, retention, controlled restore, recovery checkpoints |
| Reverse proxy | Nginx / Caddy | TLS termination, static/media, API proxy |
| SMTP | Any provider | Outbound email (verification, reset, SLA alerts) |

## Data model highlights

- `accounts.User` — email-login users with `role` (system_admin /
  it_manager / it_support / employee), `home_department`,
  `can_create_tickets`, soft-delete.
- `tickets.Ticket` — tickets with SLA due date, priority, status,
  requester, assignee, department, notes, attachments, history.
- `assets.Asset` — assets with serial number (unique), assignment,
  category, department, status, maintenance, disposal.
- `common.Notification` — in-app notifications, soft-delete.
- `common.BackgroundTaskRun` — Celery task outcome tracking.
- `common.AuditLog` — append-only audit trail (actor, action, entity).
- `common.PrivacyErasureRequest` — two-person-approval privacy erasure
  request with review/execution lifecycle.
- `common.DataRetentionPolicy` / `common.DataRetentionExecution` —
  configurable retention policies and their execution history.
- `common.HealthCheckResult` — per-component health check results.
- `common.OperationalErrorEvent` — sanitized, deduplicated application
  errors.
- `common.OperationalAlert` — deduplicated operational alerts (severity,
  acknowledgement, resolution).
- `common.OperationalIncident` — operational incidents distinct from
  support tickets.

## Security boundaries

- All object-level access is enforced in the backend (frontend hiding is
  UX only). Employees see only their own + home-department tickets/assets
  (IDOR protection).
- Attachments are stored with uuid filenames; downloads are proxied
  through permission-checked endpoints — never exposed as public URLs.
- File uploads are validated for extension, size, and executable content
  type.
- Refresh tokens are blacklisted on logout (`token_blacklist`).
- Token obtain/refresh and password-reset endpoints are rate-limited.
- Cookies default to Secure when `DEBUG=False`.

## Request flow

1. Client authenticates via JWT (access + refresh tokens).
2. API request hits Django viewset → permission check → object-level
   visibility filter → serializer validation → business logic.
3. Writes create `AuditLog` rows and `Notification` rows inline (no
   background worker required for correctness).
4. Celery beat fires periodic tasks (SLA, maintenance, email intake, and
   retention-policy evaluation); outcomes recorded in
   `BackgroundTaskRun`.

## Monitoring and observability

A centralized monitoring surface reports actual component availability rather
than configuration alone:

- `common/monitoring.py` — health checks for backend, database (connectivity,
  response time, migration consistency), Redis (cache round-trip), Celery
  worker (`inspect().ping()`), Celery beat (recent scheduled runs),
  background tasks, email (backend configured), storage (read/write probe)
  and application errors. States: healthy / degraded / unavailable /
  unknown / not configured.
- `common/monitoring_service.py` — sanitized error recording with
  deduplication, alert deduplication, acknowledgement/resolution, and
  incident management.
- `common/monitoring_metrics.py` — lightweight API performance middleware
  aggregating counts, response times and status distribution into cache (no
  per-request DB write).
- `common/monitoring_tasks.py` — scheduled Celery tasks for component health
  evaluation, repeated-failure detection and missed scheduled-task
  detection.
- `common/monitoring_views.py` — health, tasks, errors, alerts, incidents,
  API performance, and email/storage APIs (IT staff / System Admin only).

## Backup and disaster recovery (`backup` app)

The `backup` app (`/api/backup/`) automates database, media and full
backups, verification, retention, and controlled restore. It reuses Location
A's existing infrastructure and does **not** introduce a separate monitoring
application or duplicate monitoring models.

- **Database backups**: SQLite uses `sqlite3.Connection.backup()` (online
  backup API, WAL-aware, consistent snapshot; checksum computed only after
  the artifact is written and connections closed). PostgreSQL uses
  `pg_dump \| gzip` when the binaries are available; missing dependencies
  are reported clearly and credentials never surface in logs or responses.
- **Media backups**: `tar.gz` of `MEDIA_ROOT`. Restore validates every
  archive member (rejects absolute paths, path traversal, symlinks, hard
  links, devices), extracts into a temp staging directory, then merges into
  `MEDIA_ROOT` without deleting unrelated files.
- **Restore (controlled)**: System Admin only, explicit `confirm=true`, no
  concurrent restores. SQLite restores verify the checksum, validate the
  source backup, create a verified pre-restore checkpoint (restore aborts if
  it fails), restore into a temp file first, close Django connections,
  replace the live DB atomically, run `migrate --noinput`, and recover
  automatically from the checkpoint if replacement or post-replacement
  validation fails. PostgreSQL live restore is NOT automated — a documented
  DBA-assisted limitation is returned safely instead of a destructive live
  restore.
- **Monitoring integration**: backup/restore failures raise
  `common.OperationalAlert` (component `database`/`storage`) via
  `common.monitoring_service.create_or_update_alert`; outcomes and
  correlation IDs are recorded in `common.BackgroundTaskRun`.
- **Scheduling/retention**: `BackupSchedule` and `BackupRetentionPolicy`;
  the only recoverable backup of a type is never deleted, and artifacts
  referenced by a pending/running restore are protected.

## Deployment topology (production)

```
[Internet] -> [Nginx/Caddy: TLS] -> [Gunicorn: Django API]
                                    -> [React static files]
[Gunicorn] <-> [PostgreSQL]
[Celery worker] <-> [Redis] <-> [Celery beat]
[Nginx] <-> [S3-compatible object storage (private)]
[Gunicorn] -> [SMTP provider]
```

## Trust boundaries

- The backend trusts `X-Forwarded-Proto`/`X-Forwarded-For` only when
  behind a configured reverse proxy (USE_X_FORWARDED_HOST / SECURE_PROXY
  settings as needed).
- The frontend is served from the same origin or a CORS-allowed origin
  only — no wildcard CORS in production.
- S3 objects are private (`AWS_DEFAULT_ACL=None`); access is mediated by
  the application.
