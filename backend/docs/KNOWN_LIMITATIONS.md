# Known Limitations

This document lists known limitations of the IT Ticketing and Asset
Management System as of Phase 9. These are not bugs but architectural or
scope decisions that operators should be aware of before go-live.

## Authentication / authorization

- **IT Manager vs IT Support distinction**: IT Manager and IT Support have
  identical backend permissions in most areas. The `it_support` role exists
  for future segregation but is not yet assigned distinct capabilities.
- **User directory**: Employees can list and view other employees' profiles
  (name, email, role, department). This is intentional directory behavior
  but means personal information is visible organization-wide to
  authenticated users.
- **Role changes**: Only System Admin can change roles or
  `can_create_tickets`. IT Manager and IT Support cannot promote/demote
  users.
- **No multi-factor authentication**: JWT access/refresh only. MFA is not
  implemented.

## Email

- **Outbound email is provider-agnostic SMTP**: Works with any SMTP
  server, but has not been tested against a specific production provider.
  Send a real verification + password-reset email before go-live.
- **Inbound email (IMAP intake)**: `process_inbound_mailbox` polls a
  support mailbox. Duplicate message handling is best-effort (Message-ID
  dedup). Not tested with a real IMAP server.
- **Email delivery failures**: Caught and logged without secrets, but do
  not trigger retries at the API layer. Failed outbound mail does not
  break the request flow.

## Background jobs

- **Celery required in production**: The SLA escalation, maintenance
  reminder, and email intake tasks run via Celery worker + beat. Without
  Redis + Celery, these tasks do not run (SLA notifications, maintenance
  reminders, and inbound email processing are silent no-ops).
- **Task retries**: `check_sla_escalations` retries on exception with
  backoff. Other tasks may not have retry configured.

## Attachments / media

- **Local storage in dev**: `media/` is git-ignored. In production, set
  `STORAGE_BACKEND=s3` and configure an S3-compatible bucket.
- **No virus scanning**: Uploaded files are validated for extension,
  content type, and size, but not scanned for malware.
- **No image processing**: Photos are stored as-is; no thumbnail or
  resizing is performed.

## Database

- **Soft delete only**: Rows are soft-deleted (`is_deleted=True`) and can
  be restored via the recycle bin. Permanent deletion is System-Admin-only
  and blocked when history/assignments reference the row.
- **No database encryption at rest**: Configure PostgreSQL encryption
  (TDE or pgcrypto) at the infrastructure level if required.
- **SQLite not for production**: The dev default is SQLite. Production
  requires PostgreSQL.

## Internationalization / localization

- UI is English only. No i18n/l10n support.

## Reporting / exports

- Reports are read-only aggregations. Scheduled report delivery exists
  (CSV/XLSX/PDF/DOCX, email attachments, retry, execution history) but
  has not been tested against a real SMTP provider.
- Report exports (12 datasets) are verified against the API in
  `common.test_reports`.

## External service live-status (not tested)

The following external integrations are statically configured and
mock-tested, but have **not** been validated against live services:

- **PostgreSQL**: settings and migrations support PostgreSQL, but no live
  PostgreSQL database was used locally. CI runs a PostgreSQL 16 service
  job for migration consistency and targeted tests. Local live test was
  not performed (no PostgreSQL server available).
- **Redis / Celery**: broker and result backend are configured
  (`redis://localhost:6379/0`). `check_redis`, `check_celery_config`, and
  `check_celery_worker` commands are implemented and mock-tested. No live
  Redis or Celery worker was available locally, so live connectivity was
  not verified.
- **SMTP**: outbound email is provider-agnostic SMTP. `test_email_delivery
  --dry-run` is implemented and mock-tested. No real SMTP send was
  performed (no safe recipient authorized).
- **IMAP**: inbound intake is configured but not connected to a real
  mailbox. `check_inbound_email --connect` is implemented for read-only
  live checks. No IMAP `--connect` was performed (no credentials
  configured).
- **S3 / object storage**: `STORAGE_BACKEND=s3` is supported. No live S3
  or compatible bucket was tested.

## SMTP / IMAP / Redis / Celery (honest status)

- **SMTP live**: No — dry-run only; real send requires explicit `--send`
  and an authorized recipient.
- **IMAP live**: No — configuration-only; `--connect` not run (no
  credentials).
- **Redis live**: No — `check_redis` mock-tested; live PING not run
  (no local Redis).
- **Celery worker live**: No — `check_celery_worker` mock-tested; no live
  worker responded (expected in dev without Redis).

## Audit / compliance

- Audit logs store actor + action + entity IDs only — never erased
  personal data. However, the audit log itself is not tamper-evident
  (no signed/chained log entries).
- Privacy erasure is an initial version: it anonymizes the user and
  de-identifies history but is **not a GDPR-compliance claim**.

## Frontend

- React SPA served from static files. No server-side rendering.
- Theme is a single fixed design; no user-selectable theming.

## Deployment

- No Kubernetes manifests, Helm charts, or Dockerfiles are provided.
  Operators must provision VMs/containers and process management
  (systemd, supervisor, or equivalent) themselves.
- No auto-scaling or load-balancing configuration included.

## Testing

- Celery-dependent tests are skipped when Celery is not installed.
- Frontend tests mock the API layer; they do not exercise the real
  backend. End-to-end browser testing is not automated.
