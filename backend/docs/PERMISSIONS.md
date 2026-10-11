# Permission matrix

Source of truth: `common/permissions.py` + per-view `get_permissions` /
action-level guards. Frontend hiding is UX only; backend enforces.

| Capability | System Admin | IT Manager | IT Support | Employee |
|---|---|---|---|---|
| Login (JWT), view own profile | yes | yes | yes | yes |
| Change own `receive_ticket_emails` (`PATCH me/`) | yes | yes | yes | yes |
| Create ticket (own + dept select, reason if cross-dept) | yes | yes | yes | if `can_create_tickets` |
| View own + home-department tickets | yes (all) | all | all | own + home dept only |
| Assign / change ticket status-priority-category (incl. bulk) | yes | yes | yes | no |
| Add internal notes | yes | yes | yes | no (requester-visible only) |
| View ticket history (`tickets.view_ticket_history`) | yes | yes | if granted | no |
| Register / edit assets, categories, assign / retire (incl. bulk) | yes | yes | yes | no |
| View asset history (`assets.view_asset_history`) | yes | yes | if granted | no |
| Manage departments, import / bulk-update / activate employees | yes | yes | create-only employees* | no |
| Change roles / `can_create_tickets` | yes | no | no | no |
| View audit logs (`view_audit_logs`) | yes | no | no | no |
| Recycle Bin: list / inspect / restore | yes | no | no | no |
| Permanent (hard) delete — any entity, incl. recycle bin | yes (+confirm+reason+audit) | no | no | no |
| Bulk hard delete | NOBODY (no such endpoint) | — | — | — |

\* IT Support creating a user with role admin/manager is silently downgraded
to employee and audited.

Hard-delete rules: distinct `hard_delete` actions + `/api/recycle-bin/.../permanent/`,
all `IsSystemAdmin`, require `{"confirm": "<id>", "reason": "..."}`,
blocked (409) when history/assignments reference the row, audit-logged
independently of the deleted row.
