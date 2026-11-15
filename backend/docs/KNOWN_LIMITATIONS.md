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
  reminder, email intake, and retention-evaluation tasks run via Celery
  worker + beat. Without Redis + Celery, scheduled retention evaluation does
  not run. Retention policies can still be executed on demand via the API.
- **Retention production verification**: Redis, workers, and beat are not
  assumed operational in production without actual deployment verification.
  Test retention execution against a real Redis/Celery deployment before
  relying on scheduled retention.
- **Task retries**: `check_sla_escalations` retries on exception with
  backoff. Other tasks may not have retry configured.

## Privacy / data lifecycle

- **Not a compliance claim**: Privacy erasure and data retention are
  operational controls (anonymization, soft-delete, two-person approval,
  audit logging). They do **not** independently establish GDPR or any other
  regulatory compliance.
- **Audit logs are never auto-deleted**: `common.AuditLog` is excluded from
  all generic retention operations and must remain available for
  accountability.
- **Two-person approval is backend-enforced but UI-mediated**: Separation of
  duties is enforced in the backend/service layer; the frontend hides
  actions from unauthorized roles but is not the control boundary.
- **Automated erasure scope**: Automated execution currently supports
  `accounts.User` only. Other entity types require manual review and are
  not executed by the automated flow.
- **No tamper-evident audit log**: Audit log entries are append-only via the
  API but the log itself is not signed/chained.

## Monitoring and observability (Phase 26)

- **Health checks reflect best-effort availability**: Redis and Celery
  worker/beat health cannot always be confirmed from the API side; when they
  cannot be determined, the component is reported as `Unknown` rather than
  assumed healthy. A configured component (Redis URL, SMTP credentials, S3
  bucket) is not reported healthy until a real round-trip succeeds.
- **Celery-dependent monitoring**: Scheduled health evaluation, repeated
  failure detection and missed-task detection require Redis + Celery worker
  + beat to be operational in production. Without them, on-demand API checks
  still work but scheduled evaluation does not. Verify against a real
  deployment before relying on scheduled monitoring.
- **No Flower or external observability platform**: Monitoring is
  Django/Celery-native. No distributed tracing, metrics backend, or
  alerting manager is introduced.
- **API performance metrics are in-memory**: Aggregated API metrics live in
  Django cache (LocMem in dev, Redis in prod) and are not persisted per
  request; they are lost when the cache is cleared and are approximate under
  multiple workers.
- **Alert deduplication**: Alerts are deduplicated by component + title, so
  distinct failures that happen to share a title are merged. Review alert
  titles for specificity.
- **Incidents are separate from tickets**: Operational incidents track
  system-level issues and are not employee support tickets; linking to an
  existing ticket (`related_ticket`) is manual and optional.
- **Pre-go-live verification**: SMTP, Redis, PostgreSQL, and S3 integrations
  are not assumed operational until tested against the production-like
  environment; health endpoints report `Unknown`/`not_configured` until then.



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
- **SQLite for development, PostgreSQL for production**: The dev default
  is SQLite. Production requires PostgreSQL. The full migration chain
  (assets 0001-0018 including the serial-number uniqueness backstop in
  assets.0003) has been verified to apply from zero on both SQLite and a
  live PostgreSQL 18.4 rehearsal database. The serial-number uniqueness
  rule (optional/blank serials repeatable; non-blank serials unique across
  all assets including soft-deleted ones) is enforced by vendor-portable
  triggers created in assets.0003 and re-created after SQLite table
  rebuilds in assets.0006.

## Backup / disaster recovery (Phase 27)

- **PostgreSQL live restore is not automated**: restoring a PostgreSQL
  backup requires DBA-assisted manual `pg_restore` with connection
  termination; the API returns a documented limitation instead of attempting
  a destructive live restore. Validate the manual restore procedure against
  a production-like PostgreSQL deployment before relying on it.
- **Backup artifacts are not encrypted at rest**: protect `BACKUP_ROOT`
  (default `backend/backups/`) via operating-system/file-system permissions.
  Only metadata and checksums are returned through the API.
- **Distributed backup locking requires a shared cache**: backup locks use
  `cache.add` tokens plus a shared-DB "already running" guard. `LocMemCache`
  (the dev default) is per-process only; multi-worker production
  deployments must configure `CACHE_LOCATION` to a Redis URL so the cache
  lock is shared across workers.
- **No production validation**: no backup/restore has been executed against
  a live PostgreSQL/Redis/S3 deployment. SQLite backup/restore and media
  backup/restore are covered by automated tests, but production readiness
  (pg_dump/gzip availability, S3 artifact handling, concurrent workers) must
  be validated against the target deployment before go-live.
- **Restore is destructive by nature**: database restore replaces the live
  database file. A verified pre-restore checkpoint is created automatically
  for SQLite and used for automatic recovery if replacement or post-replace
  validation fails, but operators should still maintain an independent
  verified copy before initiating a restore.

## Internationalization / localization

- UI is English only. No i18n/l10n support.

## Reporting / exports

- Reports are read-only aggregations. Scheduled report delivery exists
  (CSV/XLSX/PDF/DOCX, email attachments, retry, execution history) but
  has not been tested against a real SMTP provider.
- Report exports (12 datasets) are verified against the API in
  `common.test_reports`.

## External service live-status

The following external integrations are statically configured and
mock-tested, but have **not** been validated against live services unless
noted below:

- **PostgreSQL 18.4**: A local live PostgreSQL server WAS available and was
  used for a migration rehearsal (`scripts\rehearse_postgresql.ps1`). The
  full migration chain applies from zero on PostgreSQL (`migrate` exit 0,
  all 18 asset migrations including 0003/0005/0006 applied), Django `check`
  and `makemigrations --check --dry-run` pass, and the serial-number
  uniqueness tests pass on both SQLite and PostgreSQL. Production
  PostgreSQL deployment is therefore **no longer blocked** by assets.0003.
  CI runs a PostgreSQL 16 service job; the fix is vendor-agnostic
  (plpgsql triggers on PostgreSQL, SQLite triggers on SQLite) and works on
  both versions.
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
- Frontend test suite (31 files / 278 tests) passes repeatedly; the
  Assets row-actions assign-modal test was stabilized (deterministic
  controlled-input interaction, no jest-dom-dependent matchers).

## Deployment

- No Kubernetes manifests, Helm charts, or Dockerfiles are provided.
  Operators must provision VMs/containers and process management
  (systemd, supervisor, or equivalent) themselves.
- No auto-scaling or load-balancing configuration included.

## Testing

- Celery-dependent tests are skipped when Celery is not installed.
- Frontend tests mock the API layer; they do not exercise the real
  backend. End-to-end browser testing is not automated.
