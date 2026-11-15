# Permission matrix

Source of truth: `common/permissions.py` + per-view `get_permissions` /
action-level guards. Frontend hiding is UX only; backend enforces.

| Capability | System Admin | IT Manager | IT Support | Employee |
|---|---|---|---|---|
| Login (JWT), view own profile | yes | yes | yes | yes |
| Change own `receive_ticket_emails` (`PATCH me/`) | yes | yes | yes | yes |
| Change own password (current password required) | yes | yes | yes | yes |
| Reset another employee's password (admin-only) | yes | no | no | no |
| Create ticket (for themselves; dept select, reason if cross-dept) | yes | yes | yes | if `can_create_tickets` |
| Bulk create tickets (same per-row rules; requester always self) | yes | yes | yes | if `can_create_tickets` (no assignee) |
| View own + home-department tickets | yes (all) | all | all | own + home dept only |
| Assign / change ticket status-priority-category-resolution-notes (incl. bulk) | yes | yes | yes | no |
| Supply assignee at creation | yes | yes | yes | no (403; omitted/null ok) |
| Assignee eligibility (anyone setting one) | must exist, non-deleted, active | must exist, non-deleted, active | must exist, non-deleted, active | must exist, non-deleted, active |
| Edit own/visible ticket title, description, department, asset, notes | yes | yes | yes | yes (staff-only fields → 403) |
| Edit employee details per-row (`PATCH users/<id>/`) | yes | yes | yes | no (403) |
| View employee detail overview (assets, tickets, audit) | yes | yes | yes | no |
| Soft-delete tickets, single (`DELETE /api/tickets/<id>/`) and bulk (`bulk_delete/`) | yes | yes | yes | no (403) |
| Add internal notes | yes | yes | yes | no (requester-visible only) |
| View ticket history (`tickets.view_ticket_history`) | yes | yes | if granted | no |
| Register / edit assets, categories, assign / retire / mark lost (incl. bulk) | yes | yes | yes | no |
| View asset history (`assets.view_asset_history`) | yes | yes | if granted | no |
| Schedule / update asset maintenance, view maintenance records | yes | yes | yes | read-only (authenticated) |
| Initiate / approve / reject / complete asset disposal | yes | yes | yes | no |
| View management dashboard (`common/dashboard/`) | yes | yes | yes | no |
| View department report + export operational datasets | yes | yes | yes | no |
| View SLA report (`tickets/sla-report/`) | yes | yes | yes | no |
| Configure SLA targets (`tickets/sla/`) | yes | no | no | no |
| Manage departments, import / bulk-update / activate employees | yes | yes | create-only employees* | no |
| Change roles / `can_create_tickets` | yes | no | no | no |
| View audit logs (`view_audit_logs`) | yes | no | no | no |
| Recycle Bin: list / inspect / restore | yes | no | no | no |
| Permanent (hard) delete — any entity, incl. recycle bin | yes (+confirm+reason+audit) | no | no | no |
| Bulk hard delete | NOBODY (no such endpoint) | — | — | — |
| Search / view published KB articles (`/api/common/knowledge-base/`) | yes | yes | yes | yes |
| Export knowledge_base dataset (CSV/XLSX/PDF/DOCX) | yes | yes | yes | yes |
| Submit article for review / approve / reject / publish / archive KB | yes | yes | yes | no (403) |
| View KB revision history, compare, restore | yes | yes | yes | no (403) |
| Create privacy-erasure request (`privacy-erasures/`) | yes | no | no | no |
| Independently approve / reject privacy-erasure request | yes | no | no | no |
| Execute an approved privacy-erasure request | yes | no | no | no |
| View / create / edit / enable-disable retention policies | yes | no | no | no |
| Preview / execute retention policy; view execution history | yes | no | no | no |
| View system health (`/api/common/health/`) | yes | yes | yes | no |
| View health check history | yes | yes | yes | no |
| View background task history | yes | yes | yes | no |
| Retry a safe background task | yes | no | no | no |
| View application errors | yes | yes | yes | no |
| Resolve an application error | yes | yes | yes | no |
| View operational alerts | yes | yes | yes | no |
| Create / acknowledge / resolve an alert | yes | yes | yes | no |
| Close an alert | yes | no | no | no |
| View operational incidents | yes | yes | yes | no |
| Create / delete an incident | yes | no | no | no |
| Update an incident | yes | assigned only | assigned only | no |
| View API performance | yes | yes | yes | no |
| View email & storage health | yes | yes | yes | no |
| View backups, schedules, retention, readiness | yes | yes | yes | no |
| Create / verify backups, manage schedules and retention | yes | no | no | no |
| Initiate a restore (confirm-gated, no concurrent restores) | yes | no | no | no |
\* IT Support creating a user with role admin/manager is silently downgraded
to employee and audited.

Hard-delete rules: distinct `hard_delete` actions + `/api/recycle-bin/.../permanent/`,
all `IsSystemAdmin`, require `{"confirm": "<id>", "reason": "..."}`,
blocked (409) when history/assignments reference the row, audit-logged
independently of the deleted row.

## Privacy erasure — separation of duties

- A System Admin creates the request (`pending_review`).
- A *different* System Admin must independently approve or reject. The
  requester can never approve or reject their own request (enforced in the
  backend, not only the frontend).
- Execution requires an `approved` request and is performed by a System
  Admin. The Celery retention/erasure tasks independently re-verify
  authorization before mutating anything.
- Rejection requires a reason; approval and rejection are recorded with
  reviewer identity and timestamp in `AuditLog`.
- Changing `scope`/`reason` after approval invalidates the approval
  (back to `pending_review`, reviewer cleared).

## Monitoring — permission notes

All monitoring endpoints are enforced in the backend (`IsITStaff` for read,
`IsSystemAdmin` for create / destructive / close actions). Frontend hiding of
navigation entries is UX only; the backend is the control boundary. Sensitive
diagnostic information (connection strings, credentials, tokens, request
bodies) is never stored or returned.
