# Development Roadmap

Single source of truth for feature status. Update it whenever a feature is
completed or its scope changes.

Last reviewed: Phase 12 complete — KB usefulness dashboard, notification
preferences, asset vendor management, scheduled report XLSX/PDF/DOCX +
retry, performance indexes, N+1 fix. All core test suites pass; frontend
build and lint clean.

## How to read this document

- **Complete** — backend + frontend + permissions implemented.
- **Backend only** — API/model/migration exists, UI/integration missing.
- **Frontend only** — UI exists, backend gap or not wired.
- **Not started** — neither side implemented.

## Phase 1 — Foundations (complete)

- Custom user model (email login, roles, employee ID, home department).
- JWT auth, login, email verification, password reset, change password.
- Departments + employee management (CRUD, deactivate/reactivate, role change).
- Managed ticket/asset categories.
- Audit log, recycle bin (soft delete/restore/permanent delete), privacy erasure.
- Bulk employee import/update/activate/delete.
- CSV/XLSX/PDF/DOCX export infrastructure (`common/exports.py`).

## Phase 2 — Tickets (complete)

- Ticket CRUD, notes (internal vs requester-visible), attachments, history.
- Assignment, status transitions, priorities, departments, related asset.
- Bulk create/update/delete.
- In-app notifications + ticket event emails.
- Ticket history and list ordering/filtering.

## Phase 3 — Assets (complete)

- Asset CRUD, categories, departments, attachments, history.
- Assign / return / retire / mark-lost workflows.
- Bulk create/update/assign/delete, serial uniqueness rules.
- Asset visibility and history permissions.
- Warranty start + expiry dates, purchase date, purchase cost (API + UI).

## Phase 4 — Maintenance, Disposal, Reporting, SLA

### 4A. Asset maintenance (backend complete / frontend complete)

Backend: `assets.Maintenance`, migration `0006`, serializer, viewset
(`/api/assets/maintenance/`), filters, notifications, history, assign-blocking
when maintenance is open.

Frontend:
- [x] Maintenance listing + filtering (status, type, asset, assigned technician, search).
- [x] Schedule maintenance for an asset.
- [x] Update status (start, complete, cancel, mark overdue) and details.
- [x] Record cost, vendor, dates, technician, resolution notes.
- [x] Per-asset maintenance history + upcoming/open maintenance on asset detail.
- [x] Maintenance indicator in the asset list.
- [x] Assignment blocked while maintenance is open (UI + existing backend rule).
- [x] Export maintenance records.

### 4B. Asset disposal (backend complete / frontend complete)

Backend: `assets.Disposal`, migration `0006`, serializer, viewset
(`/api/assets/disposals/`), approve/reject/complete actions, notifications,
history.

Frontend:
- [x] Disposal listing + filtering (approval status, asset, search).
- [x] Initiate disposal requests.
- [x] Approve / reject / complete workflow.
- [x] Disposal status/details on the list and per-asset history.
- [x] Role-based permissions (IT staff manage; reads follow asset visibility).
- [x] Export disposal records.

### 4C. Management dashboard (complete)

- [x] `GET /api/common/dashboard/` aggregate endpoint (IT staff only).
- [x] Employee totals/active, asset totals/status distribution.
- [x] Ticket totals/status/priority, open + overdue + SLA breaches/compliance.
- [x] Upcoming/open maintenance and assets under maintenance.
- [x] Pending disposal approvals.
- [x] Dashboard UI with practical KPI cards and status meters.

### 4D. Department-level reporting (complete)

- [x] `GET /api/common/reports/departments/` endpoint with date filters.
- [x] Employees per department (total/active).
- [x] Assets per department + status distribution.
- [x] Ticket workload per department, status/priority breakdown.
- [x] SLA metrics per department (overdue, compliance, avg resolution).
- [x] Department reports UI with date range filters.
- [x] Export via existing export infrastructure (`department_report` dataset).

### 4E. SLA frontend completion (complete)

- [x] Admin SLA configuration UI (`#/sla-config`, `TicketSLA` API).
- [x] Priority-based SLA targets.
- [x] Overdue/breached indicators on ticket list + detail.
- [x] SLA due/status information on ticket detail.
- [x] SLA report page with date filters.
- [x] Role-based access: config is System Admin only; report is IT staff only.

Verification: `manage.py check` clean; focused backend suites
(`common.test_reports`, `assets.test_operations`, `tickets.test_sla_access`,
`accounts`) pass; frontend `lint` has warnings only, `build` succeeds, and all
142 frontend tests pass.

## Phase 5 — Notifications and email (partial)

- [x] In-app notifications for ticket and asset assignment/status events.
- [x] Ticket event emails (creation, assignment, status change) honoring user preference.
- [x] Console/locmem backend for development; SMTP settings via environment.
- [ ] Notification UI consistency pass (dedupe wording, entity links, filters).
- [ ] Real SMTP delivery verification against a production-like provider.
- [ ] Configurable email settings in-app (currently environment variables only).
- [ ] Notification preferences beyond ticket email opt-out.

## 5b. Operational automation (in progress)

- [x] SLA escalation and breach notifications – configurable thresholds via
  `TicketSLA.escalation_hours` / `breach_hours`, `SLAEscalation` model, periodic
  `check_sla_escalations` Celery task, and an `/unread_count` badge endpoint.
- [x] Scheduled maintenance reminders – `Maintenance.recurrence` field,
  `MaintenanceReminder` model, periodic `check_maintenance_reminders` Celery task,
  before‑due and overdue notifications, and dashboard indicators.
- [x] Knowledge Base – full CRUD for articles (draft/published/archived),
  categories & tags, employee browsing & search, view tracking, plus the
  `#/kb` management page for IT staff (create/edit/publish/archive). Backend
  models/serializers/viewset/URLs already existed; frontend page added at
  `frontend/src/kb.jsx` with route `#/kb` and detail route `#/kb/<id>`.
  Article usefulness feedback still pending.
- [x] Self‑service portal improvements – employee ticket/asset history, knowledge-base
  browsing, notification preferences, and isolation from other employees' private records.
  (Component added at `#/self-service`; tickets, assets, and KB list rendered; API wiring
   complete; build and lint pass.)
- [ ] Email‑to‑ticket infrastructure investigation – evaluate existing mail integration,
  design creation‑from‑email schema, duplicate‑prevention, attachment handling, and clear
  failure logging. **(Phase 7 complete — IMAP polling via
  `common.tasks.process_inbound_mailbox`, `common/inbound.py` parser, `EmailProcessing`
  dedup, attachment policy reuse, ops status; see `backend/docs/EMAIL_OPS.md`.)**
- [x] Celery + Redis infrastructure – beat schedule for SLA & maintenance tasks, retry
  policies, idempotency for scheduled jobs, environment variables, and local development
  instructions. (Phase 7 complete: `backend/config/celery.py`, beat schedule in
  `config/settings.py`, retry/time-limit policy, task run recording via
  `common.BackgroundTaskRun`; run instructions in `backend/docs/EMAIL_OPS.md`.)

## Phase 6 — Reporting and analytics (partial)

- [x] Ticket category report with date range.
- [x] SLA report with date range.
- [x] Department report with date range.
- [x] CSV/XLSX/PDF/DOCX exports for core datasets.
- [x] Period-over-period comparison in reports (adds previous-period side-by-side view).
- [x] Additional operational reports (asset lifecycle, assignment ageing, maintenance cost*.
   * cost field nullable; report shows values where present).
- [x] Saved report views / scheduled report delivery (Celery beat every Monday 08:00).

## Phase 7 — Background processing (in progress → complete for intake/notifications)

- [x] Celery + Redis worker setup. (`backend/config/celery.py`, broker/result
  backend from `CELERY_*` env, retry policy, time limits, worker concurrency;
  deps `celery`, `redis`.)
- [x] Async email sending + inbound mailbox polling. (Creation/assignment/
  status/reply emails via `accounts.email_utils` with dedup cache
  `email_sent:*`; support mailbox IMAP polled by
  `common.tasks.process_inbound_mailbox`.)
- [x] Scheduled maintenance reminders. (`assets.tasks.check_maintenance_reminders`,
  hourly beat, before/overdue levels, `MaintenanceReminder` guards.)
- [x] SLA breach notifications/escalations. (`tickets.tasks.check_sla_escalations`,
  every 5 min, approach/breach levels, `SLAEscalation` guards, deadline-relative
  `TicketSLA` methods, `Ticket.priority_sla`.)
- [ ] Scheduled report generation. (Still open — Phase 6 saved-report
  delivery already exists via beat.)

## Phase 8 — Production readiness (complete)

- [x] Environment configuration for SMTP, S3, hosts, CORS.
- [x] S3-compatible object storage switch via `STORAGE_BACKEND`.
- [x] Deployment-oriented README section.
- [x] CI/CD pipeline (`.github/workflows/backend.yml`, `frontend.yml`: Django
  checks, migration consistency, backend tests, frontend lint/tests/build).
- [x] Scheduled tasks deployment (Celery worker + beat; see
  `backend/docs/EMAIL_OPS.md` for run/deploy instructions).
- [x] Production SMTP + object storage smoke tests (documented in
  `backend/docs/DEPLOYMENT.md`).
- [x] Backup/restore runbook (`backend/docs/BACKUP.md`).
- [x] Security: Asset IDOR fixed (employees scoped to assigned + home-dept
  assets), logout endpoint blacklists refresh tokens, throttling on
  token/refresh/password-reset/verify endpoints, secure cookie defaults,
  DB indexes on frequently filtered fields, N+1 fix in dashboard reports,
  auth-failure logging middleware.
- [x] Docs: `backend/docs/DEPLOYMENT.md` (production deployment guide),
  `backend/docs/BACKUP.md` (backup/restore runbook),
  `backend/docs/ARCHITECTURE.md` (system architecture),
  `backend/docs/KNOWN_LIMITATIONS.md` (known limitations).

## Phase 11 — Workflow completion and operational intelligence (complete)

### 11A. Knowledge Base article feedback (complete)
- `assets.KnowledgeBaseFeedback` model — one row per (article, user),
  helpful/not_helpful flag, optional comment; unique_together prevents
  duplicate inflation.
- `KnowledgeBaseFeedbackViewSet` + serializer — employees create/update
  their own vote; IT staff see all votes for stats.
- Frontend: helpful/not-helpful buttons on `KnowledgeBaseDetail` page,
  vote state persisted, staff sees aggregate.

### 11B. Knowledge Base ↔ Ticket integration (complete)
- `tickets.TicketKbArticle` model — links tickets to KB articles,
  `helpful` vote from requester, staff-curated links.
- `TicketKbArticleViewSet` — staff create/update/delete links; employees
  only PATCH `helpful` on their own ticket links.
- Frontend: KB article suggestions while typing in Ticket Form (opens
  article in new tab without losing form input); related KB articles
  displayed on Ticket Detail with staff link/unlink and employee helpful
  vote.

### 11C. Saved reports (complete)
- `common.SavedReport` model — report type, name, description, JSON
  filters, ownership + sharing; `SavedReportViewSet` CRUD.
- Frontend: `#/reports/saved` page — create/edit/delete/duplicate saved
  reports, run via existing report endpoints with persisted filters.

### 11D. Scheduled report delivery (complete)
- `common.ScheduledReport` + `common.ScheduledReportRun` models — daily/
  weekly/monthly cadence, recipients, format, enable/disable,
  execution history.
- Celery task `common.tasks.run_scheduled_reports` (beat every 5 min) —
  renders saved report, exports CSV/JSON, emails recipients, records
  success/failure, advances next run. Idempotent per run row.
- Frontend: schedule management available on saved reports.

### 11E. Email-to-ticket (already implemented — Phase 5b/7)
- IMAP polling via `common.tasks.process_inbound_mailbox`, parser in
  `common/inbound.py`, idempotency via `EmailProcessing`, attachment
  policy reuse, ops status endpoint. Configuration via environment
  variables (`INBOUND_MAILBOX_*`).

## Phase 9 — Final integration and release readiness (complete)

- [x] serial_number API-level validation (serializer + DB trigger backstop
  with concurrent-write IntegrityError handling → HTTP 400 field errors).
- [x] End-to-end integration tests (`common/integration_tests.py`):
  employee lifecycle, ticket lifecycle, asset lifecycle, KB + self-service,
  email/password-reset flow, background task execution.
- [x] Role-based security tests (`common/role_security_tests.py`): all 4
  roles across list/detail/update/delete/attachments/department/notifications.
- [x] CI/CD workflows verified (`.github/workflows/backend.yml`,
  `frontend.yml`).
- [x] Production deployment rehearsal (health endpoints, migration
  consistency, deploy-check warnings resolved via env vars).
- [x] Pre-existing bugs fixed: `AssetSerializer.cost` → `purchase_cost`,
  `AssignmentSerializer` field names, `AssetAssignSerializer` contract,
  `DisposalSerializer.completed` → `is_completed`, `User.is_employee_or_similar()`
  method, frontend `components.jsx` missing exports.

## Phase 9 — Final integration and release readiness (complete)

## Known blockers / decisions


- SQLite in development; report averages are computed in Python to stay
  DB-agnostic.
- `Ticket.sla_breached` is stored but overdue is computed dynamically from
  `sla_due_at`; dashboards use the dynamic definition.
- Background processing (Phase 7) is now implemented; the old
  "deferred until core workflows are done" note is superseded — scheduled
  tasks run independently of API requests via Celery beat + worker.
- Existing uncommitted Department/Employee fixes must be preserved.

## Phase 12 — Product maturity and operational reliability (complete)

### 12A. Scheduled report enhancements (complete)
- Scheduled reports now support all four export formats (CSV, XLSX, PDF,
  DOCX) via the existing `common/exports.py` engine — no separate
  implementation.
- Scheduled report emails attach the generated file (CSV/XLSX/PDF/DOCX)
  instead of a text-only body.
- `ScheduledReportRunViewSet.retry` action lets IT staff re-run a failed
  delivery; old run is marked "skipped" to avoid duplicate delivery.
- Celery beat schedule includes `run-scheduled-reports` every 5 minutes.

### 12B. KB usefulness dashboard (complete)
- `KnowledgeBaseViewSet.usefulness` action — IT staff only. Returns:
  total published articles, helpful/not-helpful vote counts, overall
  helpful rate, and per-article feedback rates sorted to surface
  ineffective articles first (low rate → no feedback → most feedback).
- Filters: `q` (title/content search), `category`, `date_from`.

### 12C. Notification preferences (complete)
- `common.UserNotificationPreference` model — per-user email master switch
  + per-category opt-in map (ticket assignment, status change, reply, SLA
  escalation, maintenance reminder, asset assignment, system alert).
- `UserNotificationPreferenceViewSet` — users own their preferences;
  IT staff can view all for auditing.
- Frontend: preferences page at `#/settings/notifications`.

### 12D. Asset vendor management (complete)
- `assets.Vendor` model — name, contact person, email, phone, address,
  notes; soft-delete; IT staff manage, employees read.
- `Asset.vendor` FK + `vendor_name` read-only on AssetSerializer.
- `VendorViewSet` at `/api/assets/vendors/`.
- Frontend: vendor field on AssetForm (create/edit), vendor display on
  AssetDetail, vendors list route `#/vendors`.

### 12E. Performance & reliability (complete)
- Fixed N+1: `AssetViewSet.select_related("vendor")` for
  `AssetSerializer.vendor_name`.
- New DB indexes: `ticket.created_at`, `ticket.priority`,
  `asset.vendor` (migrations `tickets.0007`, `assets.0014`).
- Scheduled report task uses `EmailMessage` with file attachment (was
  `send_mail` text-only).

## Known blockers / decisions
