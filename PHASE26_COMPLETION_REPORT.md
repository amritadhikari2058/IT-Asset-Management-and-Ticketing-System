# Phase 26 Completion Report — System Observability, Operational Monitoring and Reliability

## 1. Existing monitoring functionality discovered

Before implementation the project already had:
- `GET /api/common/operations/status/` — email intake counts + recent
  `BackgroundTaskRun` outcomes + Celery broker ping (`inspect().ping()`)
  + inbound mailbox config snapshot (IT staff only).
- `common.BackgroundTaskRun` — per-task-run outcome tracking (status,
  error summary, payload).
- `common.SecurityAuditMiddleware` — logs 401/403 auth failures (no
  secrets) to the `common.security` logger.
- `common.AuditLog` — append-only audit trail (used as the security-event
  store; excluded from retention).
- Celery + Redis broker/result backend + Celery beat with SLA, maintenance,
  inbound-mail and scheduled-report tasks.
- `common.notifications` — central email-preference enforcement.
- Phase 25 retention policies + executions (`DataRetentionPolicy`,
  `DataRetentionExecution`, scheduled `evaluate_retention_policies`).

These were reused and extended; nothing was duplicated or removed.

## 2. New functionality implemented

**Centralized system health dashboard** — reports actual component
availability (healthy / degraded / unavailable / unknown / not configured),
never configuration alone:
- Django backend, database (connectivity + response time + migration
  consistency), Redis (real cache round-trip), Celery worker
  (`inspect().ping()`), Celery beat (recent scheduled runs), background
  tasks, email (backend configured), storage (read/write probe), application
  errors.
- Per-component last success/failure timestamps, diagnostic info, evaluated
  timestamp; overall roll-up state.

**Database monitoring** — connectivity, `SELECT 1` response time, migration
consistency (migration loader vs. `django_migrations` table, no automatic
migrations), SQLite + PostgreSQL compatible, credentials never exposed.

**Redis + Celery monitoring** — Redis cache round-trip, Celery worker
heartbeat via `inspect()`, worker count, Celery beat evidence from recent
scheduled-task runs; reports `Unknown` when not determinable (never claims a
worker is online from configuration alone).

**Background task monitoring** — reuses `BackgroundTaskRun`: history, task
name, start/finish, duration, success/failure, sanitized error summary,
repeated-failure detection; authorized retry (`POST /api/common/tasks/retry/`)
for a safe-to-retry task list only, idempotent, records initiator.

**Application error monitoring** — `OperationalErrorEvent`: sanitized (no
passwords/tokens/PII), deduplicated by stable key (repeating exceptions
update one row), timestamps, occurrence count, correlation ID, endpoint,
status code, severity, resolve by authorized user.

**API performance monitoring** — `ApiPerformanceMiddleware` aggregates request
count, response time, slow requests, status distribution and error rates per
endpoint into Django cache (no per-request DB write, no sensitive query
params/bodies); exposed via `GET /api/common/api-performance/`.

**Operational alerts** — `OperationalAlert`: severity (informational/warning/
critical), component, description, timestamps, occurrence count,
acknowledgement/resolution, deduplicated by `dedup_key` to prevent flooding,
acknowledge/resolve/close actions with appropriate permissions.

**Operational incident management** — `OperationalIncident`: title,
description, severity, affected component, status (open/investigating/
identified/resolved/closed), assignee, timestamps, internal notes, related
alerts, optional link to an existing ticket (`related_ticket`); distinct from
employee support tickets.

**Email & storage monitoring** — included in health checks: email backend
configured (delivery not claimed without sending), storage read/write probe
and usage where measurable; private files never exposed.

**Scheduled monitoring** — Celery tasks `evaluate_component_health` (every 5
min), `detect_repeated_task_failures` (every 15 min),
`detect_missed_scheduled_tasks` (every 15 min); idempotent, non-overlapping,
record outcomes in `BackgroundTaskRun`, monitoring failures never interrupt
ticketing/asset functionality.

**Frontend** — React + Bootstrap 5 (no Tailwind) monitoring pages:
system health dashboard, component health history, background tasks (+
authorized retry), application errors, operational alerts (+ack/resolve/
close), operational incidents, API performance, email & storage health;
status indicators, filtering, pagination, loading/error/empty states, refresh,
responsive, IT staff/System Admin navigation.

## 3. Backend changes

**Models** (`backend/common/models.py`, migration `0010` + `0011`):
- `HealthCheckResult` — component, state, evaluated/last-success/last-failure
  timestamps, diagnostic, details.
- `OperationalErrorEvent` — dedup_key, component, severity, title, message,
  correlation_id, endpoint, status_code, occurrence_count, first/last
  occurred, resolved, resolved_by, details (sanitized).
- `OperationalAlert` — dedup_key (unique), component, severity, status,
  title, description, created/last occurred, occurrence count,
  acknowledged/resolved (+by/at), details.
- `OperationalIncident` — title, description, severity, status
  (open/investigating/identified/resolved/closed), affected component,
  assigned_to, created/resolved/closed timestamps, related_ticket,
  related_alerts, internal_notes.

**Migration** `common/migrations/0010_...` creates the four models;
`0011_operationalerrorevent_details.py` adds the `details` field. No
existing migrations deleted or modified.

**Services**:
- `common/monitoring.py` — `run_health_checks()` + per-component check
  functions.
- `common/monitoring_service.py` — `record_error`, `sanitize_details`/
  `sanitize_message`, `create_or_update_alert`,
  `acknowledge_alert`/`resolve_alert`/`close_alert`, `create_incident`/
  `update_incident`.
- `common/monitoring_metrics.py` — `ApiPerformanceMiddleware` + cache-based
  aggregation (`aggregate_api_metrics`).
- `common/monitoring_tasks.py` — the three scheduled Celery tasks.

**Views** (`backend/common/monitoring_views.py`):
- `system_health`, `record_application_error` (FBVs)
- `HealthCheckResultViewSet`, `BackgroundTaskMonitorViewSet` (+retry_task),
  `OperationalErrorEventViewSet` (+resolve), `OperationalAlertViewSet`
  (+create_alert/acknowledge/resolve/close),
  `OperationalIncidentViewSet` (+assign), `ApiPerformanceViewSet`,
  `EmailStorageHealthViewSet`.

**API endpoints** (`backend/common/urls.py`):
- `GET /api/common/health/`, `GET /api/common/health/results/`
- `GET /api/common/tasks/`, `POST /api/common/tasks/retry/`
- `GET /api/common/errors/`, `POST /api/common/errors/<id>/resolve/`
- `GET /api/common/alerts/`, `POST /api/common/alerts/`,
  `POST /api/common/alerts/<id>/acknowledge/`, `/resolve/`, `/close/`
- `GET|POST|GET|PATCH|DELETE /api/common/incidents/`,
  `POST /api/common/incidents/<id>/assign/`
- `GET /api/common/api-performance/`
- `GET /api/common/email-storage/`

**Permissions** — `IsITStaff` for read; `IsSystemAdmin` for create/destructive/
close; incident updates scoped to assignee (non-admins cannot change
severity/assignee). Backend-enforced; frontend hiding is UX only.

**Celery** — `common.monitoring_tasks` imported in `config/celery.py`; three
beat entries added to `CELERY_BEAT_SCHEDULE` in `settings.py`.
`ApiPerformanceMiddleware` added to `MIDDLEWARE`.

## 4. Frontend changes

- `frontend/src/monitoring.jsx` — all monitoring pages (hash-based sub-views)
  under `#/monitoring*`, IT staff/System Admin access.
- `frontend/src/monitoring.test.jsx` — 11 tests, all pass.
- `frontend/src/App.jsx` — Monitoring nav entry (Operations section,
  staffOnly), routes `#/monitoring*`, titles/crumbs.
- `frontend/src/components.jsx` — `ConfirmDialog` now accepts `children`.

## 5. Models / migrations

New models: `HealthCheckResult`, `OperationalErrorEvent`,
`OperationalAlert`, `OperationalIncident`. Migrations `0010` and `0011` (new
only; none deleted/rewritten).

## 6. Permissions and security

Backend enforcement on every endpoint. IT Manager / IT Support can view and
acknowledge/resolve; System Admin has full control including alert close and
incident create/delete. Employees have no access. Secrets/PII never stored
or returned. Alerts deduplicated to prevent flooding; no recursive alerting
from notification failure.

## 7. Celery tasks and schedules

- `common.monitoring_tasks.evaluate_component_health` — every 300 s
- `common.monitoring_tasks.detect_repeated_task_failures` — every 900 s
- `common.monitoring_tasks.detect_missed_scheduled_tasks` — every 900 s

## 8. Monitoring and alerting architecture

Health checks → `HealthCheckResult` → alerts (dedup) → incidents. Errors →
`OperationalErrorEvent` (dedup). API metrics → cache. All recorded outcomes
in `BackgroundTaskRun`. No external monitoring dependency (no Flower).

## 9. Testing

**Backend** (`manage.py test common.test_monitoring`) — 20 tests, all pass.
`manage.py check` clean; `makemigrations --check` no changes detected.

**Frontend** (`npm test`) — 31 test files passed / 31, 217 tests passed /
217, plus 1 pre-existing unhandled error in `zz-debug.test.jsx`
(confirmed pre-existing on `main` via `git stash`). `npm run lint` — no
errors (pre-existing warnings only). `npm run build` — succeeds (pre-existing
chunk-size warning only).

**Existing vs new failures** — no pre-existing backend failures introduced.
The `department_report` 500 (`KeyError: 'employees'` in
`common/reports.py`) is pre-existing and unrelated to Phase 26. The full
`common` suite is slow due to Celery task timeouts in this offline
environment (no real Redis broker), not due to Phase 26 changes.

## 10. Infrastructure integrations actually tested

None against real services: Redis, Celery worker/beat, SMTP, PostgreSQL and
S3 are not available in this environment. Health checks correctly report
`not_configured`/`Unknown` for unconfigured components rather than assuming
health. Production verification against real Redis + Celery + SMTP + S3 is
required before relying on scheduled monitoring in production.

## 11. Documentation updated

- `DEVELOPMENT_ROADMAP.md` — Phase 26 marked complete.
- `backend/docs/API_OVERVIEW.md` — monitoring endpoints documented.
- `backend/docs/PERMISSIONS.md` — monitoring permission matrix + notes.
- `backend/docs/ARCHITECTURE.md` — monitoring models, components, tasks.
- `backend/docs/DEPLOYMENT.md` — monitoring beat tasks + visibility
  endpoints added to deployment + pre-go-live context.
- `backend/docs/KNOWN_LIMITATIONS.md` — monitoring limitations documented.
- `backend/docs/PRIVACY_ERASURE.md` — unchanged (Phase 25 doc).

## 12. Git status

Branch: `main` (up to date with `origin/main`). Nothing committed, nothing
pushed; Phase 25 and Phase 26 changes remain uncommitted in the working
tree.

Modified (16): `DEVELOPMENT_ROADMAP.md`, `backend/common/models.py`,
`privacy_views.py`, `serializers.py`, `tasks.py`, `tests.py`, `urls.py`,
`config/celery.py`, `config/settings.py`, `docs/API_OVERVIEW.md`,
`ARCHITECTURE.md`, `DEPLOYMENT.md`, `KNOWN_LIMITATIONS.md`, `PERMISSIONS.md`,
`frontend/src/App.jsx`, `frontend/src/components.jsx`.

New (19): `backend/common/migrations/0010_*.py`, `0011_*.py`,
`backend/common/monitoring.py`, `monitoring_metrics.py`,
`monitoring_service.py`, `monitoring_tasks.py`, `monitoring_views.py`,
`backend/common/test_monitoring.py`, `frontend/src/monitoring.jsx`,
`frontend/src/monitoring.test.jsx` (plus the 8 Phase 25 untracked files
still present).

## 13. Known limitations

See `backend/docs/KNOWN_LIMITATIONS.md` § "Monitoring and observability".
Key points: Redis/Celery worker/beat health reported as `Unknown` when not
determinable; scheduled monitoring requires a real Redis + Celery deployment;
no external observability platform; API metrics in-memory and approximate
under multiple workers; alert deduplication by component + title; incidents
distinct from tickets; production SMTP/Redis/PostgreSQL/S3 not verified in
this environment.

## 14. Recommended next development phase

- Verify scheduled monitoring against a real Redis + Celery worker/beat
  deployment.
- Add distributed request tracing or a metrics backend (Prometheus) if
  operational visibility needs outgrow the in-memory cache approach.
- Add alert notification delivery (email/integrations) for critical alerts,
  with guardrails to avoid recursive alerting.
- Link operational incidents bidirectionally to tickets and expose incident
  status on the management dashboard.
