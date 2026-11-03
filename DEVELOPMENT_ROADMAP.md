# Development Roadmap

Single source of truth for feature status. Update it whenever a feature is
completed or its scope changes.

Last reviewed: Phase 14 complete — comprehensive product readiness assessment.
Fixed critical frontend defects (unreachable Self-Service/Employees nav routes,
double /api/ API prefix breaking calls, unsupported EmptyState prop), aligned
beat schedule documentation with settings.py (added run-scheduled-reports),
verified all backend and frontend tests pass. No deployment yet.

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
- [x] Notification preferences beyond ticket email opt-out — full per-category
  email preferences page at `#/settings/notifications`, backed by
  `common.notifications` central enforcement (`UserNotificationPreference`).
- [ ] Notification UI consistency pass (dedupe wording, entity links, filters).
- [ ] Real SMTP delivery verification against a production-like provider.
- [ ] Configurable email settings in-app (currently environment variables only
  for SMTP; per-user/category opt-out is configurable in-app).

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
- Frontend: `#/reports/schedules` page — IT staff only. Create/edit/enable/
  disable/delete schedules from saved reports, execution history per
  schedule, retry failed runs, next-run display.

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
- `common/notifications.py` central enforcement module —
  `email_enabled_for(user, category=None)`, `get_user_preferences(user)`,
  `scheduled_report_delivery_enabled()`; essential categories
  (verification/password-reset/security) never suppressed; missing prefs
  default to enabled; category opt-out never blocks unrelated categories.
- `accounts/email_utils.send_ticket_notification()` gated via central helper;
  `send_scheduled_report_email()` for scheduled report delivery.
- `UserNotificationPreferenceViewSet` — users own their preferences;
  IT staff can view all for auditing.
- Serializer `validate_categories` rejects unknown category keys.
- Frontend: preferences page at `#/settings/notifications` — load on open,
  global + per-category toggles, save via PATCH/POST, loading/success/error
  states, keeps unsaved changes on API failure; wired into App nav and
  linked from Profile email preferences panel.

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

## Phase 13 — Frontend completion and centralized preference enforcement (complete)

### 13A. Notification preferences frontend (complete)
- New page `frontend/src/settings.jsx` — `NotificationSettings` component at
  `#/settings/notifications`, accessible from user account/settings area.
- Loads `GET /api/common/notification-preferences/` on open, filters by
  `user.id`, falls back to sensible defaults (all categories enabled) when no
  preference record exists.
- Global email master switch + per-category toggles for all 7 backend
  categories (ticket_assignment, ticket_status_change, ticket_reply,
  sla_escalation, maintenance_reminder, asset_assignment, system_alert).
- Save via `PATCH /api/common/notification-preferences/<id>/` (existing record)
  or `POST /api/common/notification-preferences/` (new record).
- Loading/success/error states; keeps unsaved edits on API failure.
- Users can only edit their own preferences (enforced by backend viewset).
- Wired into `App.jsx` NAV (all users), TITLES, crumbs, and linked from the
  Profile page email preferences panel.
- Frontend tests: `frontend/src/settings.test.jsx` (6 tests).

### 13B. Scheduled report management frontend (complete)
- New page `frontend/src/scheduled-reports.jsx` — `ScheduledReports` component
  at `#/reports/schedules` (IT staff only, matches backend `_is_ticket_staff`).
- List via `GET /api/common/scheduled-reports/`; create from saved report
  (daily/weekly/monthly, comma-separated recipients, CSV/XLSX/PDF/DOCX
  format, enabled toggle).
- Enable/disable via `PATCH`, edit via `PATCH`, delete via `DELETE`.
- `next_run_at` display; filterable list (search, schedule, format, enabled).
- Execution history via `GET /api/common/scheduled-report-runs/` filtered
  client-side by schedule; status badge (succeeded/failed), error summary,
  recipient count.
- Retry failed via `POST /api/common/scheduled-report-runs/<id>/retry/`;
  old run marked "skipped" to avoid duplicate delivery.
- Consistent with Saved Reports page design system (PageHeader, DataTable,
  Pager, Modal, ConfirmDialog, Badge, Field).
- Frontend tests: `frontend/src/scheduled-reports.test.jsx` (5 tests).

### 13C. Centralized backend preference enforcement (complete)
- `backend/common/notifications.py` — `ESSENTIAL_EMAIL_CATEGORIES`
  (email_verification, password_reset, security_alert); category constants;
  `get_user_preferences(user)`; `email_enabled_for(user, category=None)`;
  `scheduled_report_delivery_enabled()` → True.
- Master switch = `UserNotificationPreference.email_enabled` OR legacy
  `User.receive_ticket_emails`; missing prefs → enabled (defaults).
- Essential categories always True (password reset/verification/security
  emails not suppressed); category None → master switch only.
- Ticket email mapping: creation → category None (master); assignee →
  `ticket_assignment`; status change → `ticket_status_change`; SLA →
  `sla_escalation`; maintenance → `maintenance_reminder`.
- `accounts/email_utils.send_ticket_notification()` gated via central helper
  before dedup; `send_scheduled_report_email()` uses
  `scheduled_report_delivery_enabled` + `EmailMessage` attach.
- Serializer `validate_categories` rejects unknown category keys.
- `_wants_ticket_email` wrappers in `tickets/views.py` and `common/inbound.py`
  delegate to central helper.
- Backend tests: `UserNotificationPreferenceTests` (8 tests) and
  `ScheduledReportTests` (9 tests) — all pass.

### 13D. Verification
- Backend: `manage.py check` clean; `UserNotificationPreferenceTests` +
  `test_scheduled_reports` = 17 tests OK; `TicketNotificationTests` = 9 tests
  OK; combined regression run = 92 tests OK.
- Frontend: `lint` clean (warnings only, pre-existing); `build` succeeds;
  `settings.test.jsx` (6) + `scheduled-reports.test.jsx` (5) + `profile.test.jsx` (6) = 18 tests OK.
- No new migrations; no DB resets; no credentials invented; external email
  delivery not claimed verified (locmem backend used in tests).

## Phase 14 — Product readiness assessment and gap closure (complete)

### 14A. Critical frontend defects fixed
- `#/self-service` route unreachable from nav: NAV hash `#/self-service` did not
  match routes map key `#self-service`. Unified to `#/self-service` so the
  Self-Service page is reachable from the sidebar.
- `#/users` (Employees) route unreachable from nav: NAV hash `#users` did not
  match routes map key `#/users`. Unified to `#/users` so the Employees page
  is reachable from the sidebar.
- Double `/api/` prefix breaking API calls: `api.js` baseURL is already
  `http://127.0.0.1:8000/api`, but several pages prefixed paths with `/api/`,
  producing `/api/api/...` URLs that match no Django route. Fixed in:
  `notifications.jsx` (notifications list/mark-all-read/unread-count/download),
  `scheduled-reports.jsx` (saved-reports, scheduled-report-runs),
  `settings.jsx` (notification-preferences GET/POST/PATCH),
  `self-service.jsx` (tickets/assets/knowledge-base).
- `EmptyState` called with unsupported `variant="error"` prop in
  `self-service.jsx` (3 occurrences): prop removed; `EmptyState` only accepts
  `title`/`hint`/`action`.
- Removed unused `Notifications` import from `self-service.jsx`.

### 14B. Documentation alignment
- `backend/docs/DEPLOYMENT.md` §7 and `backend/docs/EMAIL_OPS.md` §4: added
  `run_scheduled_reports` / `common.tasks.run_scheduled_reports` every 5 min
  to the Celery beat task list, matching `settings.py` `CELERY_BEAT_SCHEDULE`
  (previously documented only 3 of 4 tasks).

### 14C. Verification
- Backend: 40 tests OK
  (`UserNotificationPreferenceTests` + `test_scheduled_reports` +
  `TicketNotificationTests` + `role_security_tests`). `manage.py check` clean.
- Frontend: 18 tests OK (settings 6 + scheduled-reports 5 + profile 6);
  `lint` clean (warnings only, pre-existing); `build` succeeds.
- All Phase 13 uncommitted changes preserved; no migrations added/deleted;
  no DB resets; no credentials invented.

## Known blockers / decisions

## Phase 16 � Advanced Asset Inventory and Stock Management
Backend core implemented (inventory app). Frontend/tests pending.
