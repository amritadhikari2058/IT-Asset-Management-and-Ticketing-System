# API overview    

Base: `/api/`. Auth: `POST /api/token/` + `POST /api/token/refresh/` (JWT).
Trailing slashes required (DRF default).

## Accounts `/api/accounts/`
- `GET me/` own profile (role, `can_create_tickets`) for permission-aware
  UI; read-only.
- `PATCH me/` self-service `receive_ticket_emails` toggle only (true/false,
  default true). No other field is writable here; roles, bulk, and import
  flows never touch this flag. Verification and password-reset emails are
  independent of it.
- `POST /api/accounts/change-password/` (authenticated self only):
  `{current_password, new_password}` → 200; wrong current password → 400;
  new password validated with Django's password validators. Never logged.
- `POST /api/accounts/users/<id>/reset_password/` (System Admin only):
  `{new_password, confirm?}`. Sets a new password for the target employee via
  `set_password` (Django password validators applied; never cleartext/logged).
  Old password stops working immediately; outstanding password-reset tokens are
  invalidated and outstanding JWT refresh tokens are blacklisted (existing
  sessions must re-authenticate). Audited (`password_reset`) without secrets;
  response never exposes hashes or the new password.
- `departments/` CRUD (soft delete; 409 + references if still used). The list
  supports server-side search with `q` (name or code); each row shows member
  and asset counts.
- `users/` CRUD + `deactivate/`, `reactivate/`, `change_role/`
  (Admin-only), `hard_delete/` (Admin-only, confirm+reason).
  The list supports server-side filtering with `q` (employee ID, email, first
  or last name), `department` (ID or code), `role`, and `is_active`, plus
  `ordering` by `employee_id` or `email`.
- `users/<id>/employee_detail/` (IT staff only): GET an administrative
  overview for a single employee — the user record plus assigned assets,
  tickets requested / assigned, and recent audit activity. No passwords or
  hashes are exposed.
- `users/bulk_import/` GET template info (JSON by default; append
  `?download=csv` for a header-only CSV template file); POST `file`/`rows` with
  `preview:true` then `confirm:true` → `{successful, skipped, failed}`.
  Append `?download=csv` to the confirmation POST for a downloadable
  per-row report (`employee_import_report.csv`, columns
  `row,key,outcome,message` with `outcome` in
  `successful/skipped/failed`); JSON remains the default. The report holds
  row numbers, employee IDs, and concise error text only — never passwords
  or full row payloads. Confirmation, permissions, and per-row atomicity
  are identical for both representations.
- `users/bulk_update/` keyed on `employee_id`; role/permissions ignored.
- `users/bulk_activate/` `{ids, activate, preview, confirm}`.
- `users/bulk_delete/` SOFT delete only; history rows land in `skipped`.

## Assets `/api/assets/`
- `categories/` managed dropdown source; `+Add` modal posts here;
  delete blocked (409) while assets reference it.
- `/api/assets/` CRUD; ordinary PUT/PATCH ignores `assigned_to`
  (use `/{id}/assign/` + `/{id}/return_asset/` + `/{id}/retire/`) and
  rejects direct jumps to `assigned`/`retired`/`lost` (400; resubmitting
  the unchanged status is fine). `/{id}/mark_lost/` (IT staff) needs a
  nonblank `reason`, closes open assignments, and records history/audit
  atomically; repeating it on an already-lost asset is a no-op success.
  - **Serial numbers** stay OPTIONAL (blank is valid on any number of
    assets) but a non-blank serial must be unique across **all** assets,
    including soft-deleted ones (a recycled asset keeps reserving its
    serial so a restore can never collide). Input is trimmed, so `SN-1 `
    and `SN-1` cannot coexist. Duplicates → 400 with a field error on
    `serial_number`; the same rule is enforced in the database by
    triggers (migration `assets.0003`) for concurrent writers, bulk
    imports, and raw ORM writes that bypass DRF validation. Pre-existing
    duplicate rows are reported during `migrate`, never deleted or
    rewritten.
  - **Create with an attachment**: `POST /api/assets/` accepts an
    optional multipart `file` next to the asset fields. The file is
    validated *before* anything is saved and asset + attachment are
    written in one transaction — an invalid/oversized file (400) leaves
    no asset behind, so a retry can never create a twin. Canonical client
    flow stays two-step: create the asset, then `POST /assets/attachments/`
    with the new id. `file` on `PATCH`/`PUT` is rejected explicitly (400)
    instead of being silently dropped.
- `assignments/history/?asset=<id>`, `histories/?asset=<id>`
  (permission-gated).
- `maintenance/` CRUD (IT staff write; reads authenticated). Filters:
  `asset`, `status`, `maintenance_type`, `assigned_to`, `open=true`, and
  `q` (title, asset tag/name, vendor). Each row exposes `is_overdue` and
  writes asset history + audit + in-app notifications. Assigning an asset
  with open maintenance (scheduled/in_progress/overdue) is blocked (409).
- `disposals/` CRUD + `approve/`, `reject/`, `complete/` (IT staff only).
  Filters: `asset`, `approval_status`, `disposal_method`,
  `completed=true|false`, and `q` (asset tag/name, reason). A disposal can
  only be completed after approval; completion closes open assignments,
  clears the holder, sets the asset `disposed`, and writes history/audit.
- `attachments/` asset files: same storage abstraction, UUID names, and
  validation as ticket attachments. Upload/edit/delete need IT staff;
  list/download follow asset visibility (permission-checked, no public
  URLs). Soft delete keeps bytes; permanent deletion unlinks the file
  only when no retained record references it.
- `bulk_create/` (template via GET: JSON by default, `?download=csv` for a
  header-only CSV file; confirmation POST also accepts `?download=csv`
  for a per-row `asset_import_report.csv` with columns
  `row,key,outcome,message`), `bulk_update/` (rejects assignment
  keys), `bulk_delete/` (soft-only, history rows skipped).
  - Unreadable uploads (binary/invalid UTF-8 CSV, corrupt or fake XLSX,
    empty file) → **400** `{file: [...]}` JSON with the generic reason;
    the exception detail goes to the server log only — never a Django
    error page.
  - `serial_number` is checked in both directions: preview reports
    `duplicate serial number <sn>` per row (existing rows *and* other rows
    in the same file), confirm skips those rows with the same message,
    and `bulk_update/` refuses to move an asset onto an occupied serial
    (the row lands in `failed`, nothing is written).
- `bulk_assign/` explicit bulk assignment (the ONLY bulk assignment path):
  POST `{"assignments": [{"asset_tag", "employee_id", "note"?}], ...}`
  with `preview:true` (default; validates, writes nothing) then
  `confirm:true` → `{successful, skipped, failed, summary}`. Per-row
  validation: required keys, existence (soft-deleted reported as such),
  in-request duplicates, active employees only, `available` status only;
  already-assigned assets land in `skipped` (return first, never silently
  overwritten). Each success writes an `Assignment` row, sets assignee +
  `assigned` status, and records asset history + audit atomically.

## Tickets `/api/tickets/`
- `categories/` managed dropdown; same 409 rule; usable immediately
  after POST (no restart needed).
- `/api/tickets/` CRUD (single `DELETE` requires IT staff; employees get
  403); cross-department filing needs `on_behalf_reason`; a non-null
  `assignee` must be an existing, non-deleted, active user (else 400);
  employees supplying an assignee at creation get 403 (omitted/null
  stays valid); single updates commit ticket + history + audit +
  notifications atomically, with status mail sent after commit (failures
  swallowed, never rolling back); creation commits ticket + history +
  audit + notification atomically, with creation mails sent after
  commit;
  invalid status transitions → 400; `notes/` sub-action filters
  `is_internal` for employees. Single-ticket updates: changing
  `assignee`/`status`/`priority`/`category` requires IT staff (403 for
  employees); resubmitting unchanged values and editing other fields is
  allowed. `bulk_update/` is IT-staff-only (403 otherwise). Staff may set
  `resolution_notes` (e.g. when resolving/closing); employees get 403 on
  any change to it, and resubmitted unchanged values still pass.
- `histories/?ticket=<id>` (permission-gated), `attachments/`
  (soft delete).
- Resolution timestamps: `resolved_at`/`closed_at` are read-only and
  follow **real** status transitions on both the single-ticket path and
  `bulk_update/`: → `resolved` stamps `resolved_at`, → `closed` stamps
  `closed_at`, → `reopened`/`in_progress`/`open` clears both. Resubmitting
  the current status (or editing other fields) never touches them, and a
  rejected transition leaves them unchanged.
- `bulk_create/` IT-staff gate is NOT applied: anyone who may create
  tickets may bulk-create (employees: own tickets only, no assignee).
  POST `{"tickets": [{title, description, category, priority?,
  department?, on_behalf_reason?, asset?, assignee?}], preview?,
  confirm?}` → `{successful: [{row, id, title}], skipped: [],
  failed: [{row, errors}], summary}`. Preview (default) validates without
  writing; `confirm:true` executes each valid row in its own transaction
  (save + history + audit + notification), emails afterwards (failures
  swallowed). Requester is always the caller; cross-department
  justification and assignee-eligibility rules match single creation.
- `bulk_update/` `{ids, changes: {assignee,priority,category,status}}`
  per-ticket transition validation → `{successful, skipped, failed}`;
  a non-null assignee that is unknown, deleted, or inactive fails that
  row (never a silent unassign); explicit null still unassigns.
- `bulk_delete/` soft-only, IT-staff-only (employees get 403).
- `reports/by-category/?date_from&date_to` → per-category
  `{total, open_count, closed_count, high_count, critical_count, urgent}`
  (ORM aggregation; `urgent` = high + critical, kept for compatibility;
  zero-match categories omitted). No period comparison is computed —
  the endpoint only filters the selected range (see limitation below).
- List sorting: `?ordering=` allowlist per list (unknown values fall back
  to the default order) with a unique tie-break so pages are stable:
  tickets `created_at` (default newest-first), `priority` (by severity,
  not alphabetically), `status`; assets `asset_tag` (default), `name`,
  `status`; employees `employee_id` (default), `email`. Prefix `-` for
  descending (e.g. `?ordering=-priority`).

## Common `/api/common/` + recycle bin
- `dashboard/` (IT staff): management aggregates — employees, asset status
  distribution, ticket status/priority, open/overdue/SLA compliance,
  upcoming/open maintenance, assets under maintenance, pending disposals.
  Optional `date_from`/`date_to` filter ticket metrics.
- `reports/departments/` (IT staff): per-department employees, assets,
  ticket workload, status/priority breakdown, SLA overdue/breach/compliance,
  and average resolution hours. Optional `date_from`/`date_to` filter ticket
  metrics.
- `exports/<dataset>/` supports the existing datasets plus `maintenance`,
  `disposals`, `department_report`, and `knowledge_base` (authenticated; the
  knowledge-base dataset only ever exports published articles).
- `knowledge-base/` (GET, authenticated): employee-facing search over published
  Knowledge Base articles. Returns paginated `{count, next, previous, results}`.
  Query params: `q` (title/summary/content/tag/category search), `category`
  (id or code), `tag` (slug). Employees never receive drafts, pending-review,
  approved-but-unpublished, or archived articles.
- `audit-logs/` (Admin read-only; filterable by `action` from the
  logged action set, exact `entity_type`, and ISO `date_from`/`date_to`;
  unknown actions and malformed dates → 400), `notifications/` (own only).
- Ticket workflows create in-app notifications inline with history/audit:
  new assignment → assignee; status change → requester; requester-visible
  note → requester + assignee. The actor is never notified of their own
  action; internal-note content never enters notifications.
- Asset assignment and return create in-app notifications only (new holder
  on assign, previous holder on return; never the actor, never inactive or
  deleted recipients; successes only — never preview/skipped/failed rows).
  Asset events send no email and ignore email preferences.
- The three ticket-event emails (creation mail to requester, assignment
  mail to assignee, status-change mail to requester) are each skipped when
  that recipient set `receive_ticket_emails: false`. In-app notifications
  are unconditional; verification/reset emails ignore the flag.
- `POST notifications/mark_all_read/` → `{updated: N}` for the caller's
  own unread, non-deleted notifications (idempotent; not dismissal).
- `GET /api/common/operations/status/` (IT staff/admin): operational
  visibility — inbound email health (last successful processing, pending/
  failed counts, processed-today, totals via `common.EmailProcessing`),
  background task health (`celery_healthy` broker ping + last 20
  `common.BackgroundTaskRun` outcomes), and inbound mailbox configuration
  snapshot.
- `GET /api/recycle-bin/?entity_type&date_from&date_to&deleted_by`
- `GET /api/recycle-bin/<type>/<id>/` → record + `blocked[]` reasons.
- `POST .../restore/` → 200 or 409 `{blockers}` (pass `force:true` to
  override with audit).
- `POST|DELETE .../permanent/` Admin-only, needs
  `{"confirm": "<id>", "reason": "..."}`; 409 + `impact` when history
  exists; writes independent `AuditLog` first.

## Privacy erasure `/api/common/privacy-erasures/` (System Admin only)

Two-person-approval data lifecycle governance. A request is created in
`pending_review` state, must be independently approved by a second System
Admin (the requester can never approve their own request), and only then
can be executed. Erasure anonymizes personal data and preserves
de-identified history; PII is never logged.

- `GET /api/common/privacy-erasures/` — list requests. Supports `status`,
  `entity_type`, `requested_by`, `reviewed_by`, `date_from`, `date_to`,
  `q` (search scope/reason/entity/object ID), `ordering`, `page`,
  `page_size`. Paginated.
- `GET /api/common/privacy-erasures/<id>/` — detail: request, reviewer,
  executor, dependency/retention analysis, audit history.
- `POST /api/common/privacy-erasures/` — create. Body:
  `{"entity_type", "object_id", "scope", "reason", "confirm": "<object_id>"}`.
  `confirm` must match `object_id`. Target must exist and be a supported
  entity type (`accounts.User` automated). Returns `pending_review`.
- `POST /api/common/privacy-erasures/<id>/approve/` — independent approve.
  Body `{"decision": "approve", "reason": "..."}`. Requires an active
  System Admin who is not the requester. 409 if not pending review or
  self-approval.
- `POST /api/common/privacy-erasures/<id>/reject/` — independent reject.
  Body `{"decision": "reject", "reason": "..."}`. Reason required.
  409 if not pending review or self-rejection.
- `POST /api/common/privacy-erasures/<id>/execute/` — execute an approved
  request. Body `{"confirm": "<object_id>"}`. Requires `approved` status +
  independent approval. Transactional and idempotent (re-executing a
  completed request is a success). Anonymizes PII, soft-deletes the
  target, preserves history.
- `POST /api/common/privacy-erasures/<id>/cancel/` — cancel a
  non-terminal request. Body `{"reason": "..."}` (optional).
- `PATCH|PUT /api/common/privacy-erasures/<id>/` — update `scope` and/or
  `reason`. Changing scope/reason on an approved request invalidates the
  approval (returns to `pending_review`, reviewer cleared) so it must be
  re-approved before execution.
- `GET /api/common/privacy-erasures/<id>/dependency_preview/` —
  dependency/retention analysis for the target.

## Data retention `/api/common/retention-policies/` (System Admin only)

Configurable retention policies for operational data categories. Audit
logs (security events) are never automatically deleted.

- `GET|POST /api/common/retention-policies/` — list / create policies.
  Fields: `name`, `data_category`, `retention_duration` (days), `enabled`,
  `conditions`, `description`, `responsible_admin`.
- `GET|PATCH|PUT|DELETE /api/common/retention-policies/<id>/` — manage a
  policy.
- `GET /api/common/retention-policies/<id>/preview/` — preview eligible /
  excluded records without mutating anything.
- `POST /api/common/retention-policies/<id>/execute/` — execute a policy
  (soft-deletes eligible records respecting soft-delete). Revalidates
  eligibility at execution time. Disabled policies cannot execute.
- `GET /api/common/retention-executions/` — execution history
  (eligible / affected / excluded counts, error summary).

## Bulk safety (all bulk endpoints)
1. Server permission check. 2. Row validation. 3. Preview + count.
4. `confirm:true` required. 5. Per-row atomic (partial success).
6. `{successful, skipped, failed}` summary. 7. Audit per row.
8. No generic field endpoint — only explicit whitelists.

## Bulk safety (all bulk endpoints)
1. Server permission check. 2. Row validation. 3. Preview + count.
4. `confirm:true` required. 5. Per-row atomic (partial success).
6. `{successful, skipped, failed}` summary. 7. Audit per row.
8. No generic field endpoint — only explicit whitelists.

## System monitoring `/api/common/` (IT staff/admin only)

The monitoring surface reports *actual* component availability, not
configuration alone. A configured-but-unreachable component is reported as
`unavailable` or `unknown`, never `healthy` merely because environment
variables are set. Health states: `healthy`, `degraded`,
`unavailable`, `unknown`, `not_configured`.

- `GET /api/common/health/` — centralized health dashboard: per-component
  state + overall state, last success/failure timestamps and diagnostics.
  Components: backend, database, Redis, Celery worker, Celery beat,
  background tasks, email, storage, application errors.
- `GET /api/common/health/results/` — health check result history, filterable
  by `component` and `state`.
- `GET /api/common/operations/status/` — email intake + background task health
  + Celery broker ping (existing endpoint).
- `GET /api/common/tasks/` — background task execution history
  (`BackgroundTaskRun`), filterable by `task_name` and `status`.
- `POST /api/common/tasks/retry/` (System Admin) — re-enqueue a safe-to-retry
  task (`{task_name}`). Only tasks in the safe-retry list may be retried;
  arbitrary task names/arguments are never accepted. Idempotent: a running
  run blocks a duplicate enqueue. Records who initiated the retry.
- `GET /api/common/errors/` — sanitized, deduplicated application errors
  (`OperationalErrorEvent`). Passwords, tokens and PII are never stored;
  repeating exceptions increment `occurrence_count` on one row.
  `POST /api/common/errors/<id>/resolve/` (IT staff) marks resolved.
- `GET /api/common/alerts/` — operational alerts (`OperationalAlert`),
  deduplicated by `dedup_key` so persistent failures do not flood.
  Severity: informational/warning/critical. `POST /api/common/alerts/`
  (System Admin) creates one. `POST /api/common/alerts/<id>/acknowledge/`
  and `/resolve/` (IT staff), `/close/` (System Admin).
- `GET /api/common/incidents/` — operational incidents distinct from employee
  support tickets (`OperationalIncident`). Statuses: open, investigating,
  identified, resolved, closed. `POST` (System Admin) creates; assignee-scoped
  updates; optionally linked to an existing ticket via `related_ticket`.
- `GET /api/common/api-performance/` — aggregated API request counts, response
  times, error rates and status distribution per endpoint (collected in cache,
  no per-request DB write). `?minutes=` window.
- `GET /api/common/email-storage/` — email backend and file/media storage
  health (read/write probe, storage usage where measurable). Private files are
  never exposed.

## Backup / disaster recovery `/api/backup/` (System Admin / IT staff)

Database, media and full backups with SHA-256 checksum verification,
schedules, retention and controlled restore. Only metadata and checksums are
returned — no filesystem paths or credentials. Backend permissions are
enforced; frontend hiding is UX only.

- `GET|POST /api/backup/backups/` — list backups / trigger an on-demand
  backup (`backup_type`, `verify`). System Admin to create.
- `POST /api/backup/backups/<id>/verify/` — recompute SHA-256 and confirm
  the artifact exists and is readable (System Admin).
- `POST /api/backup/backups/run-retention/` — expire backups past retention
  and delete eligible artifacts (System Admin).
- `GET|POST /api/backup/restores/` — list restores / initiate a restore
  (`backup_id`, `confirm=true`). System Admin only; requires explicit
  confirmation; blocked while another restore is in progress.
- `GET|POST|PATCH|PUT|DELETE /api/backup/schedules/` — backup schedules
  (System Admin). Drives Celery Beat entries via `backup.tasks.sync_beat_schedules`.
- `GET|POST|PATCH|PUT|DELETE /api/backup/retention/` — retention policies
  (`retention_days`, `keep_min_count`) (System Admin).
- `GET /api/backup/readiness/` — recovery readiness snapshot (status, latest
  successful/verified backup, backup age, 24h failure counts).

Restore behavior: SQLite restores verify the recorded checksum, validate the
source with `PRAGMA integrity_check`/`quick_check`, create a verified
pre-restore checkpoint (restore aborts if it fails), restore into a temp file
first, replace the live DB atomically, run `migrate --noinput`, and recover
automatically from the checkpoint if replacement or post-replacement
validation fails. PostgreSQL live restore is NOT automated — a clear
documented limitation is returned instead (manual `pg_restore` with DBA
assistance).

Restore audit: every restore is recorded in `RestoreOperation`
(initiator, backup used, start/complete, duration in seconds, checkpoint,
failure details, correlation ID). Failures raise
`common.OperationalAlert` and are recorded in `common.BackgroundTaskRun`.

## Reporting limitation
`reports/by-category/` filters exactly the requested `date_from`/`date_to`
range and returns absolute counts. No previous-period comparison or
percentage changes are computed — absolute counts only, by decision.
