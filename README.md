# Ticket and Asset Management System

Django 6 + DRF backend (`backend/`) and React (Vite) frontend (`frontend/`).
No cloud services, S3 credentials, or real SMTP needed for local development.

## Quick start (local)

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_defaults   # 7 ticket cats, 6 asset cats, 3 depts, 4 demo users
python manage.py runserver        # API at http://127.0.0.1:8000/api/

cd ../frontend
npm install
npm run dev                      # UI at http://localhost:5173
```

Demo logins (passwords in `seed_defaults.py`): `admin@local`,
`manager@local`, `support@local`, `employee@local`.

## Environment variables

Copy nothing — local dev works with defaults. For production set:

| Variable | Default (dev) | Purpose |
|---|---|---|
| `SECRET_KEY` | committed dev key | Long random string; **required in production** (boot refuses `DEBUG=False` without it) |
| `DEBUG` | true | Set `false` in production |
| `ALLOWED_HOSTS` | empty (local runserver) | Comma-separated production hostnames |
| `CORS_ALLOWED_ORIGINS` | both localhost:5173 origins | Comma-separated frontend origins |
| `CSRF_TRUSTED_ORIGINS` | empty | Only needed for cross-origin session-auth cookie use |
| `EMAIL_BACKEND` | console (dev) / smtp (prod) | `django.core.mail.backends.smtp.EmailBackend` in prod |
| `EMAIL_HOST` / `EMAIL_PORT` | empty / 587 | SMTP server |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | empty | SMTP credentials (never commit) |
| `EMAIL_USE_TLS` / `EMAIL_USE_SSL` | true / false | TLS/SSL (exactly one) |
| `EMAIL_TIMEOUT` | 10 | SMTP timeout (s) |
| `DEFAULT_FROM_EMAIL` / `SERVER_EMAIL` | noreply@localhost | Sender addresses |
| `FRONTEND_URL` | http://localhost:5173 | Verification/reset links + ticket links |
| `BACKEND_URL` | http://127.0.0.1:8000 | API links in emails |
| `STORAGE_BACKEND` | local | `s3` in production (needs `django-storages` + `boto3` there only) |
| `AWS_STORAGE_BUCKET_NAME` / `AWS_S3_REGION_NAME` | empty | Production bucket |
| `AWS_S3_ENDPOINT_URL` | empty | Only for S3-compatible providers (MinIO etc.) |
| `AWS_QUERYSTRING_EXPIRE` | 3600 | Signed-URL TTL (unused: downloads are proxied) |
| `ATTACHMENT_ALLOWED_EXTENSIONS` | pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx | Upload whitelist |
| `ATTACHMENT_MAX_SIZE_MB` | 10 | Upload size cap |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | redis://localhost:6379/0 | Celery broker / result backend (Redis) |
| `CELERY_TASK_MAX_RETRIES` / `CELERY_TASK_RETRY_BACKOFF` / `CELERY_TASK_TIME_LIMIT` / `CELERY_CONCURRENCY` | 3 / 60 / 300 / 4 | Task retry, backoff, time limit, worker concurrency |
| `CACHE_LOCATION` | *(empty)* | Redis URL for the cache (outbound email dedup) in multi-process setups |
| `INBOUND_MAILBOX_ENABLED` | true | Support-mailbox IMAP intake switch |
| `INBOUND_MAILBOX_HOST` / `INBOUND_MAILBOX_PORT` / `INBOUND_MAILBOX_USER` / `INBOUND_MAILBOX_PASSWORD` / `INBOUND_MAILBOX_USE_TLS` / `INBOUND_MAILBOX_NAME` / `INBOUND_SUPPORT_MAILBOX` / `INBOUND_ALLOWED_SENDER_DOMAINS` / `INBOUND_MAILBOX_POLL_SECONDS` | — / 993 / — / — / true / INBOX / support@example.com / *(empty)* / 60 | Support mailbox (IMAP) intake settings |
| `EMAIL_DEDUP_TTL_SECONDS` | 3600 | Outbound ticket-email dedup window (seconds) |

## Background processing (Celery + Redis)

- Email intake polls the support mailbox over IMAP via
  `common.tasks.process_inbound_mailbox` (beat every 60s; `\Seen` only set
  after successful processing, so failures are safely retried).
- Scheduled SLA escalations (`tickets.tasks.check_sla_escalations`, every
  5 min) and maintenance reminders (`assets.tasks.check_maintenance_reminders`,
  hourly) run as periodic Celery tasks and record outcomes in
  `common.BackgroundTaskRun`.
- Ops visibility: `GET /api/common/operations/status/` (IT staff/admin) for
  inbound email + task health.
- Full details: `backend/docs/EMAIL_OPS.md`.

Local development:

```bash
# terminal 1 — worker
celery -A config.celery worker --loglevel=info --concurrency=4

# terminal 2 — beat scheduler
celery -A config.celery beat --loglevel=info
```

Redis must be running locally (or set `CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND`, `CACHE_LOCATION` to a managed Redis). See
`backend/docs/EMAIL_OPS.md` for production deployment notes.

## Email

* Dev/test: console backend (dev) / locmem (tests). No delivery attempted.
* Prod: plain Django SMTP backend — no SES/SendGrid SDKs required; any
  SMTP provider works. Delivery failures are caught, logged without secrets
  (no passwords, tokens, or message bodies), and never break the request.
* Password-reset request always returns the same message so it never reveals
  whether an address has an account.
* Email delivery has been exercised with Django's test backend
  (`common/tests.py::EmailFlowTests`). It is **not claimed to work with any
  real provider until tested against production-like SMTP** — set the vars
  above and send a real verification + reset before go-live.

## Attachments

* Dev: local `media/` (git-ignored). Prod: set `STORAGE_BACKEND=s3` plus the
  `AWS_*` vars — no application code changes (uses Django storage API).
* Files are private: no public URLs are ever generated; downloads go through
  `GET /api/tickets/attachments/<id>/download/` with ticket-visibility
  checks. Filenames are uuid-based (`attachment_upload_to`), original names
  kept only as metadata. Extensions, executable content-types, and size are
  validated; `ATTACHMENT_*` vars configure policy.
* Soft delete keeps the bytes; restore re-exposes them; permanent delete
  unlinks the object only when no retained record references the same stored
  file. Never commit `media/`, `.env`, or credentials.

## Privacy erasure (initial version)

* System-Admin-only: `POST /api/common/privacy-erasures/` with
  `{entity_type, object_id, scope, reason, confirm: "<object_id>"}` →
  `GET /<id>/` shows dependency/retention check → `POST /<id>/execute/`
  (confirm again) or `/reject/`.
* Execution anonymizes the user (email/username/name/phone/job-title
  replaced, password unusable, deactivated, soft-deleted) and preserves
  history de-identified. The audit log stores IDs + scope only — never the
  erased personal data.
* `reviewed_by` exists for a future two-person-approval step; it is not
  enforced yet. This workflow alone is **not a GDPR-compliance claim**.

## Key docs

* `backend/docs/API_OVERVIEW.md` — endpoints, bulk safety rules.
* `backend/docs/PERMISSIONS.md` — role matrix (backend-enforced).
