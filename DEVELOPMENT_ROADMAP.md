# Development Roadmap

Single source of truth for feature status. Update it whenever a feature is
completed or its scope changes.

Last reviewed: Phase 8 in progress — email-to-ticket intake, outbound
notifications, Celery/Redis background processing, and ops status endpoint
shipped with focused backend tests (`common.test_phase7`).

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
- [ ] Knowledge Base – create/edit/publish/archive articles, categories & tags,
  employee browsing & search, view tracking, "solved?" feedback, and integration into
  ticket creation.
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

## Phase 8 — Production readiness (partial)

- [x] Environment configuration for SMTP, S3, hosts, CORS.
- [x] S3-compatible object storage switch via `STORAGE_BACKEND`.
- [x] Deployment-oriented README section.
- [ ] CI/CD pipeline (lint, tests, build).
- [x] Scheduled tasks deployment (Celery worker + beat; see
  `backend/docs/EMAIL_OPS.md` for run/deploy instructions).
- [ ] Production SMTP + object storage smoke tests.
- [ ] Backup/restore runbook.

## Known blockers / decisions

- SQLite in development; report averages are computed in Python to stay
  DB-agnostic.
- `Ticket.sla_breached` is stored but overdue is computed dynamically from
  `sla_due_at`; dashboards use the dynamic definition.
- Background processing (Phase 7) is now implemented; the old
  "deferred until core workflows are done" note is superseded — scheduled
  tasks run independently of API requests via Celery beat + worker.
- Existing uncommitted Department/Employee fixes must be preserved.
