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
  (use `/{id}/assign/` + `/{id}/return_asset/` + `/{id}/retire/`).
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
- `/api/tickets/` CRUD; cross-department filing needs `on_behalf_reason`;
  invalid status transitions → 400; `notes/` sub-action filters
  `is_internal` for employees.
- `histories/?ticket=<id>` (permission-gated), `attachments/`
  (soft delete).
- `bulk_update/` `{ids, changes: {assignee,priority,category,status}}`
  per-ticket transition validation → `{successful, skipped, failed}`.
- `bulk_delete/` soft-only.
- `reports/by-category/?date_from&date_to` → per-category
  `{total, open_count, closed_count, high_count, critical_count, urgent}`
  (ORM aggregation; `urgent` = high + critical, kept for compatibility;
  zero-match categories omitted). No period comparison is computed —
  the endpoint only filters the selected range (see limitation below).

## Common `/api/common/` + recycle bin
- `audit-logs/` (Admin read-only), `notifications/` (own only).
- Ticket workflows create in-app notifications inline with history/audit:
  new assignment → assignee; status change → requester; requester-visible
  note → requester + assignee. The actor is never notified of their own
  action; internal-note content never enters notifications.
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
