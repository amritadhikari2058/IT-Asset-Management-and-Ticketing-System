# Production Deployment Guide

This guide covers deploying the IT Ticketing and Asset Management System to
production. The architecture is:

- **Backend**: Django 6 + DRF API, Gunicorn, PostgreSQL, Redis (Celery
  broker/result backend + cache)
- **Frontend**: React (Vite) built to static assets, served by the reverse
  proxy or a CDN
- **Background jobs**: Celery worker + Celery beat
- **Storage**: S3-compatible object storage for media (attachments, photos)

**The development SQLite configuration is NOT suitable for production.**

## 1. Provision infrastructure

| Service | Purpose | Production choice |
|---------|---------|-------------------|
| Database | Application data | PostgreSQL 15+ |
| Cache / broker | Celery + Django cache | Redis 7+ |
| Object storage | Attachments, photos | S3-compatible (AWS S3, MinIO) |
| SMTP | Outgoing email | Any SMTP provider |
| Reverse proxy | TLS termination, static/media | Nginx or Caddy |
| Process manager | Gunicorn + Celery | systemd, supervisor, or Kubernetes |

## 2. Backend configuration

Copy `.env.example` to `.env` (outside the repo) and set production values:

```ini
# Core
DEBUG=false
SECRET_KEY=<long random string — required>
ALLOWED_HOSTS=tickets.example.com,api.tickets.example.com

# Security cookies (HTTPS)
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SECURE_SSL_REDIRECT=true
SECURE_HSTS_SECONDS=31536000
CSRF_TRUSTED_ORIGINS=https://tickets.example.com

# CORS (frontend origin only, no wildcards)
CORS_ALLOWED_ORIGINS=https://tickets.example.com

# Database (PostgreSQL, not SQLite)
DATABASE_URL=postgres://user:pass@db:5432/tickets

# Storage — S3 in production
STORAGE_BACKEND=s3
AWS_STORAGE_BUCKET_NAME=your-bucket
AWS_S3_REGION_NAME=us-east-1
AWS_S3_ENDPOINT_URL=https://s3.example.com   # only for S3-compatible (MinIO)
AWS_DEFAULT_ACL=None
AWS_S3_FILE_OVERWRITE=False

# Email (SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=<from env>
EMAIL_HOST_PASSWORD=<from env>
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=noreply@example.com
SERVER_EMAIL=alerts@example.com

# URLs (HTTPS in production)
FRONTEND_URL=https://tickets.example.com
BACKEND_URL=https://api.tickets.example.com

# Cache (Redis for multi-process)
CACHE_LOCATION=redis://redis:6379/1

# Backup / disaster recovery (Phase 27)
BACKUP_ROOT=/var/backups/tickets   # protected; separate from MEDIA_ROOT

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
CELERY_TASK_TIME_LIMIT=300
CELERY_CONCURRENCY=4

# Attachment policy
ATTACHMENT_ALLOWED_EXTENSIONS=pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx
ATTACHMENT_MAX_SIZE_MB=10

# Logging
LOG_LEVEL=INFO
```

Django database configuration: the settings file defaults to SQLite. For
production, add a `DATABASES` block that reads `DATABASE_URL` (e.g. via
`dj-database-url` or manual parsing) and uses `django.db.backends.postgresql`.

## 3. Configuration validation

Before deploying, run the production configuration validator:

```bash
cd backend
python manage.py validate_production_config
```

Normal mode exits 0 when there are no ERROR results (warnings are
acceptable for local development). Strict mode treats development-acceptable
settings as production errors:

```bash
python manage.py validate_production_config --strict
```

Local development will correctly fail strict validation (DEBUG, SQLite,
console email backend, etc.). This is expected — strict mode is for
production-like environments only.

Also run Django's built-in deployment check:

```bash
python manage.py check --deploy
```

Review each warning: some are expected under local settings (e.g.
`security.W018` DEBUG=True) and are resolved by production environment
variables (see `.env.example`). Do not suppress warnings merely to produce
a clean command.

### Environment distinction

| Environment | DEBUG | ALLOWED_HOSTS | Cookies | SSL redirect | HSTS |
|---|---|---|---|---|---|
| Local development | true | (empty) | insecure | false | 0 |
| Test / CI | false | test hosts | insecure | false | 0 |
| Production (HTTPS) | false | explicit hostnames | secure | true | 31536000+ |
| Behind TLS proxy | false | explicit hostnames | secure | false* | 31536000+ |

\* When behind a reverse proxy that terminates TLS, set
`SECURE_PROXY_SSL_HEADER` instead of `SECURE_SSL_REDIRECT=true`, and trust
the proxy via `CSRF_TRUSTED_ORIGINS` / `CORS_ALLOWED_ORIGINS`.

## 4. Install dependencies

```bash
cd backend
pip install -r requirements.txt
# Production-only extras (add to requirements if deploying via pip):
# pip install dj-database-url psycopg2-binary gunicorn
```

```bash
cd ../frontend
npm ci
npm run build   # -> frontend/dist/
```

## 5. Run migrations and seed

```bash
cd backend
python manage.py migrate
python manage.py seed_defaults   # optional: demo data
```

Run `migrate` on every deploy after code changes.

### PostgreSQL migration rehearsal

Production requires PostgreSQL; local development uses SQLite. Before a
production deploy, rehearse migrations against an empty PostgreSQL database
using the provided script:

```powershell
# From the repository root (PowerShell):
.\scripts\rehearse_postgresql.ps1 -DatabaseName ticketing_rehearsal -ConfirmRehearsal
```

Safeguards:
- Refuses production-looking database names (`postgres`, `template0`,
  `production`, `prod`, `live`, `primary`, `ticketing`, `ticketing_prod`,
  `app_db`, `main`).
- Requires the explicit `-ConfirmRehearsal` flag.
- Never creates or drops a database automatically; the rehearsal database
  must already exist and be empty.
- Never touches the local SQLite database.
- Runs `manage.py check`, `makemigrations --check --dry-run`, `migrate`,
  and targeted backend tests against PostgreSQL.

Verification: the rehearsal was run against a live PostgreSQL 18.4 database
and the full migration chain (including assets.0003/0005/0006 serial-number
uniqueness triggers) applied from zero; the serial-number uniqueness tests
pass on both SQLite and PostgreSQL. The script is vendor-agnostic and works
with PostgreSQL 16 (CI) and 18.4 (local rehearsal).

The script is run in CI against a disposable PostgreSQL service (see
`.github/workflows/backend.yml`, `postgres` job). Credentials are supplied
via environment variables only and are never printed.

## 6. Serve the backend (Gunicorn)

```bash
cd backend
gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

Run behind a reverse proxy (Nginx/Caddy) that terminates TLS. Do not expose
Gunicorn directly to the internet.

## 7. Serve the frontend

The Vite build produces static assets in `frontend/dist/`. Serve them with
the reverse proxy, and proxy `/api/` to the Gunicorn backend:

```nginx
location /api/ { proxy_pass http://127.0.0.1:8000; }
location /   { root /path/to/frontend/dist; try_files $uri /index.html; }
```

The frontend's `api.js` hardcodes `http://127.0.0.1:8000/api` in dev. In
production, set the axios baseURL via build env or serve the frontend from
the same origin as the API so relative calls work.

## 8. Celery worker and beat

```bash
# Worker
celery -A config.celery worker --loglevel=info --concurrency=4

# Beat (scheduler)
celery -A config.celery beat --loglevel=info
```

Run worker and beat as separate systemd services (or Kubernetes
Deployments). Beat runs the periodic tasks:
- `check_sla_escalations` every 5 minutes
- `run_scheduled_reports` every 5 minutes
- `check_maintenance_reminders` hourly
- `process_inbound_mailbox` every minute (if `INBOUND_MAILBOX_ENABLED=true`)
- `evaluate_component_health` every 5 minutes (system health checks)
- `detect_repeated_task_failures` every 15 minutes
- `detect_missed_scheduled_tasks` every 15 minutes

### Celery and Redis diagnostics

The following management commands validate configuration without contacting
a worker (safe for CI):

```bash
# Celery configuration: broker, serializer, accept_content, Beat tasks,
# time limits, retry settings.
python manage.py check_celery_config

# Celery worker availability (inspect ping; short timeout).
python manage.py check_celery_worker

# Redis broker: harmless PING only; never lists, reads, or deletes keys.
python manage.py check_redis --timeout 5
```

- `check_redis` performs only a `PING`, sanitizes credentials in output,
  and returns nonzero on DNS/connection/authentication/timeout failures.
- `check_celery_worker` uses `inspect ping` and returns nonzero when no
  worker responds; it never enqueues work.
- None of these commands print credentials or broker URLs with secrets.

## 9. Static and media files

- **Static**: `python manage.py collectstatic` → `STATIC_ROOT`
  (`backend/staticfiles/`). Serve via the reverse proxy at `/static/`.
- **Media**: stored in S3 (private). Downloads go through the
  permission-checked attachment endpoints — never expose S3 URLs directly.
  Set `AWS_DEFAULT_ACL=None` so objects are private by default.

## 10. HTTPS and domain

- Terminate TLS at the reverse proxy with a valid certificate (Let's
  Encrypt or your provider).
- Set `SECURE_SSL_REDIRECT=true`, `SECURE_HSTS_SECONDS`, and secure cookies.
- Add the domain to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- Set `CORS_ALLOWED_ORIGINS` to the production frontend origin only.

## 11. Environment variables and secrets

Never commit `.env`, database files, or credentials to Git. Use a secrets
manager (AWS Secrets Manager, HashiCorp Vault, GitHub Secrets for CI) and
inject at runtime.

Required minimum in production:
- `SECRET_KEY`
- `DEBUG=false`
- `ALLOWED_HOSTS`
- `DATABASE_URL` (PostgreSQL)
- `EMAIL_HOST_*` / SMTP credentials
- `AWS_STORAGE_BUCKET_NAME` + region (if `STORAGE_BACKEND=s3`)
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` (Redis)

## 12. Health endpoints

Two endpoints are available for load balancer / orchestration probes:

- `GET /health/` — liveness (always 200 if the app is running)
- `GET /ready/` — readiness (checks database connectivity; 503 if DB is
  unavailable)

## 13. Logging and monitoring

Django logs to stdout (captured by systemd / container runtime). Log level
is controlled by `LOG_LEVEL` (default INFO). Celery worker/beat logs go to
their own stdout.

Operational visibility endpoints (IT staff/admin only):

- `GET /api/common/operations/status/` — email intake + background task
  health + Celery broker ping.
- `GET /api/common/dashboard/` — dashboard KPIs.
- `GET /api/common/health/` — centralized system health (per-component state:
  backend, database, Redis, Celery worker/beat, background tasks, email,
  storage, application errors). Reflects actual availability, not just
  configuration.
- `GET /api/common/health/results/` — health check result history.
- `GET /api/common/tasks/` — background task execution history; `POST
  /api/common/tasks/retry/` (System Admin) re-enqueues a safe-to-retry task.
- `GET /api/common/errors/` — sanitized, deduplicated application errors;
  `POST /api/common/errors/<id>/resolve/` (IT staff) marks resolved.
- `GET /api/common/alerts/` — operational alerts; `POST
  /api/common/alerts/<id>/acknowledge/`, `/resolve/` (IT staff), `/close/`
  (System Admin); `POST /api/common/alerts/` create (System Admin).
- `GET /api/common/incidents/` — operational incidents (CRUD; System Admin
  create/delete, assignee-scoped updates).
- `GET /api/common/api-performance/` — aggregated API request counts, response
  times and error rates (no per-request DB writes).
- `GET /api/common/email-storage/` — email and storage health detail.

Monitor:
- Celery worker heartbeat (beat schedule running)
- `BackgroundTaskRun` table for recent task outcomes
- `EmailProcessing` table for inbound email intake
- `HealthCheckResult` / `OperationalAlert` / `OperationalIncident` /
  `OperationalErrorEvent` tables for monitoring state
- Disk usage of media (dev) / S3 bucket size (prod)

## 14. SMTP and IMAP diagnostics

### Outbound email (SMTP)

Outbound email uses Django's SMTP backend (provider-agnostic). Delivery
failures are logged without credentials or message bodies and never break
the request flow. Send a real verification + password-reset email against
the production-like SMTP provider before go-live.

Configuration-only (safe, no mail sent):

```bash
python manage.py test_email_delivery --dry-run
```

Explicit real-send (requires both `--to` and `--send`; never automatic):

```bash
python manage.py test_email_delivery --to ops@example.com --send
```

The command prints the backend class, sender, SMTP host/port/TLS/SSL
settings, and (presence-only) username/password status. Credentials are
never printed. It exits nonzero on send failure and distinguishes SMTP
acceptance from inbox delivery.

### Inbound email (IMAP)

Configuration check:

```bash
python manage.py check_inbound_email
```

Optional read-only live connectivity (does not fetch bodies, mark messages
read, move, delete, or create tickets):

```bash
python manage.py check_inbound_email --connect
```

The command reports enablement, host, port, username, password presence,
TLS/SSL, mailbox, and poll interval. With `--connect`, it performs a
read-only IMAP `SELECT` only and returns nonzero on DNS/timeout/auth/
mailbox-selection failures. Credentials are never printed.

## 15. Pre-go-live checklist

- [ ] `DEBUG=false` and a unique `SECRET_KEY` set
- [ ] `ALLOWED_HOSTS` contains production hostnames only
- [ ] `SESSION_COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true`
- [ ] `SECURE_SSL_REDIRECT=true`, HSTS configured
- [ ] PostgreSQL (not SQLite) configured and migrated
- [ ] Redis running for Celery + cache
- [ ] S3 bucket private (`AWS_DEFAULT_ACL=None`)
- [ ] SMTP tested with a real verification + reset email
- [ ] `collectstatic` run; static files served
- [ ] Gunicorn + Celery worker + beat running as services
- [ ] `/health/` and `/ready/` return OK
- [ ] `.env` / secrets not in Git; `media/` and `db.sqlite3` git-ignored
- [ ] CI pipeline passing (lint, tests, build)

## 16. Do not

- Do not auto-deploy or push changes without authorization.
- Do not run destructive backup/restore against the live database without a
  verified copy.
- Do not log passwords, tokens, SMTP credentials, or sensitive user data.

## 17. Backup / disaster recovery (`backup` app)

The `backup` app (`/api/backup/`) automates database, media and full
backups, verification, retention and controlled restore. It is wired into
the existing Celery Beat via `backup.tasks.sync_beat_schedules` (Phase 26
beat entries are never clobbered).

### Configuration
- `BACKUP_ROOT` — artifact directory (default `backend/backups/`). Protect
  with OS permissions; it is separate from `MEDIA_ROOT` and is not exposed
  publicly through the API. Only metadata + checksums are returned.
- `pg_dump`, `pg_restore` and `gzip` — required on PATH for PostgreSQL
  backups. When absent, PostgreSQL backups are recorded as failed with a
  clear message rather than silently succeeding.

### Operational notes
- SQLite backups use `sqlite3.Connection.backup()` (WAL-aware, consistent
  snapshot). PostgreSQL live restore is NOT automated — a documented
  DBA-assisted limitation is returned safely instead of a destructive live
  restore (`pg_restore` requires connection termination by a DBA).
- Distributed backup locking requires a shared cache backend (Redis).
  `LocMemCache` (the dev default) is per-process only, so configure
  `CACHE_LOCATION` to a Redis URL for multi-worker production deployments.
- Backup artifacts are not encrypted at rest by the application; protect
  `BACKUP_ROOT` via filesystem permissions.
