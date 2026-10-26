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
- `departments/` CRUD (soft delete; 409 + references if still used).
- `users/` CRUD + `deactivate/`, `reactivate/`, `change_role/`
  (Admin-only), `hard_delete/` (Admin-only, confirm+reason).
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
- `GET /api/recycle-bin/?entity_type&date_from&date_to&deleted_by`
- `GET /api/recycle-bin/<type>/<id>/` → record + `blocked[]` reasons.
- `POST .../restore/` → 200 or 409 `{blockers}` (pass `force:true` to
  override with audit).
- `POST|DELETE .../permanent/` Admin-only, needs
  `{"confirm": "<id>", "reason": "..."}`; 409 + `impact` when history
  exists; writes independent `AuditLog` first.

## Bulk safety (all bulk endpoints)
1. Server permission check. 2. Row validation. 3. Preview + count.
4. `confirm:true` required. 5. Per-row atomic (partial success).
6. `{successful, skipped, failed}` summary. 7. Audit per row.
8. No generic field endpoint — only explicit whitelists.

## Reporting limitation
`reports/by-category/` filters exactly the requested `date_from`/`date_to`
range and returns absolute counts. No previous-period comparison or
percentage changes are computed — absolute counts only, by decision.
