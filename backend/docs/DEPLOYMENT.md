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

## 3. Install dependencies

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

## 4. Run migrations and seed

```bash
cd backend
python manage.py migrate
python manage.py seed_defaults   # optional: demo data
```

Run `migrate` on every deploy after code changes.

## 5. Serve the backend (Gunicorn)

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

## 6. Serve the frontend

The Vite build produces static assets in `frontend/dist/`. Serve them with
the reverse proxy, and proxy `/api/` to the Gunicorn backend:

```nginx
location /api/ { proxy_pass http://127.0.0.1:8000; }
location /   { root /path/to/frontend/dist; try_files $uri /index.html; }
```

The frontend's `api.js` hardcodes `http://127.0.0.1:8000/api` in dev. In
production, set the axios baseURL via build env or serve the frontend from
the same origin as the API so relative calls work.

## 7. Celery worker and beat

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

## 8. Static and media files

- **Static**: `python manage.py collectstatic` → `STATIC_ROOT`
  (`backend/staticfiles/`). Serve via the reverse proxy at `/static/`.
- **Media**: stored in S3 (private). Downloads go through the
  permission-checked attachment endpoints — never expose S3 URLs directly.
  Set `AWS_DEFAULT_ACL=None` so objects are private by default.

## 9. HTTPS and domain

- Terminate TLS at the reverse proxy with a valid certificate (Let's
  Encrypt or your provider).
- Set `SECURE_SSL_REDIRECT=true`, `SECURE_HSTS_SECONDS`, and secure cookies.
- Add the domain to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- Set `CORS_ALLOWED_ORIGINS` to the production frontend origin only.

## 10. Environment variables and secrets

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

## 11. Health endpoints

Two endpoints are available for load balancer / orchestration probes:

- `GET /health/` — liveness (always 200 if the app is running)
- `GET /ready/` — readiness (checks database connectivity; 503 if DB is
  unavailable)

## 12. Logging and monitoring

Django logs to stdout (captured by systemd / container runtime). Log level
is controlled by `LOG_LEVEL` (default INFO). Celery worker/beat logs go to
their own stdout.

Operational visibility endpoints (IT staff/admin only):
- `GET /api/common/operations/status/` — email intake + background task
  health + Celery broker ping
- `GET /api/common/dashboard/` — dashboard KPIs

Monitor:
- Celery worker heartbeat (beat schedule running)
- `BackgroundTaskRun` table for recent task outcomes
- `EmailProcessing` table for inbound email intake
- Disk usage of media (dev) / S3 bucket size (prod)

## 13. SMTP configuration

Outbound email uses Django's SMTP backend (provider-agnostic). Delivery
failures are logged without credentials or message bodies and never break
the request flow. Send a real verification + password-reset email against
the production-like SMTP provider before go-live.

## 14. Pre-go-live checklist

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

## 15. Do not

- Do not auto-deploy or push changes without authorization.
- Do not run destructive backup/restore against the live database without a
  verified copy.
- Do not log passwords, tokens, SMTP credentials, or sensitive user data.
