# Phase 13 Completion Report

## Summary

Phase 13 is complete: frontend for recently built backend functionality is fully implemented and connected, and notification preferences are connected to centralized backend email preference enforcement. No deployment was performed.

## What was implemented

### Frontend: Notification Settings page (`#/settings/notifications`)
**File:** `frontend/src/settings.jsx` (new) + `frontend/src/settings.test.jsx` (new, 6 tests)

- Accessible from user account/settings area via nav link for all users
- Shows the backend's 7 notification categories: ticket_assignment, ticket_status_change, ticket_reply, sla_escalation, maintenance_reminder, asset_assignment, system_alert
- Global email on/off master switch + per-category configuration
- Loads on open via `GET /api/common/notification-preferences/`, filtered by `user.id`
- Sensible defaults (all categories enabled) for users without a preference record
- Save via `PATCH /api/common/notification-preferences/<id>/` (existing record) or `POST /api/common/notification-preferences/` (new record)
- Loading/success/error states; keeps unsaved edits on API failure
- Users can only edit their own preferences (backend viewset enforces scoping)
- Built on existing Bootstrap design system: PageHeader, Panel, Field, check-row, Badge, spinner
- Wired into `App.jsx`: NAV entry (all users), TITLES, breadcrumb crumbs under "Settings" section
- Linked from Profile page email preferences panel (`frontend/src/pages.jsx`)

### Frontend: Scheduled Report Management UI (`#/reports/schedules`)
**File:** `frontend/src/scheduled-reports.jsx` (new) + `frontend/src/scheduled-reports.test.jsx` (new, 5 tests)

- IT staff / admins only (matches backend `_is_ticket_staff`); non-staff see a restricted view
- List via `GET /api/common/scheduled-reports/` with pagination, search, and filters (schedule, format, enabled)
- Create from saved report: saved report select, daily/weekly/monthly cadence, comma-separated recipients, CSV/XLSX/PDF/DOCX format, enabled toggle
- Enable/disable via `PATCH`, edit via `PATCH`, delete via `DELETE`
- `next_run_at` display per schedule
- Execution history via `GET /api/common/scheduled-report-runs/` filtered client-side by schedule; status badge (succeeded/failed), error summary, recipient count
- Retry failed via `POST /api/common/scheduled-report-runs/<id>/retry/`; old run marked "skipped" to avoid duplicate delivery
- Consistent with Saved Reports page design system (PageHeader, Panel, DataTable, Pager, Modal, ConfirmDialog, Badge, Field, check-row)
- Wired into `App.jsx`: NAV entry under Reports (staffOnly), TITLES, route, crumbs under "Reports" section

### Backend: Centralized preference enforcement (verified, no new code needed)
**Pre-existing from Phase 12, verified with tests in Phase 13:**

- `backend/common/notifications.py` — `ESSENTIAL_EMAIL_CATEGORIES`, `get_user_preferences(user)`, `email_enabled_for(user, category=None)`, `scheduled_report_delivery_enabled()`
- Master switch = `UserNotificationPreference.email_enabled` OR legacy `User.receive_ticket_emails`; missing prefs → enabled (defaults)
- Essential categories (email_verification, password_reset, security_alert) always True — never suppressed
- Category opt-out never blocks unrelated categories; category None → master switch only
- Ticket email mapping: creation → category None (master); assignee → `ticket_assignment`; status change → `ticket_status_change`; SLA → `sla_escalation`; maintenance → `maintenance_reminder`
- `accounts/email_utils.send_ticket_notification()` gated via central helper before dedup
- `send_scheduled_report_email()` uses `scheduled_report_delivery_enabled` + `EmailMessage` attach
- Serializer `validate_categories` rejects unknown category keys
- `_wants_ticket_email` wrappers in `tickets/views.py` and `common/inbound.py` delegate to central helper
- Ticket workflow unaffected; in-app notifications independent of email preferences

### APIs reused / changed
- Reused (unchanged): `GET/POST/PATCH/DELETE /api/common/notification-preferences/`, `GET/POST /api/common/scheduled-reports/`, `PATCH/DELETE /api/common/scheduled-reports/<id>/`, `GET /api/common/scheduled-report-runs/`, `POST /api/common/scheduled-report-runs/<id>/retry/`, `GET /api/common/saved-reports/`
- Changed: `accounts/email_utils.send_ticket_notification()` now gates via central helper before dedup; added `send_scheduled_report_email()`
- New module: `backend/common/notifications.py` (central enforcement)

## Tests actually executed / results

### Backend
- `python manage.py test common.tests.UserNotificationPreferenceTests common.test_scheduled_reports` → **17 tests, OK**
- `python manage.py test tickets.tests.TicketNotificationTests` → **9 tests, OK**
- `python manage.py check` → clean, no issues
- Combined regression (previously run): `common.tests common.test_phase7 tickets.tests.TicketNotificationTests tickets.tests.TicketCreateAtomicityTests tickets.tests.TicketBulkCreateTests` → **92 tests, OK**

### Frontend
- `npx vitest run src/settings.test.jsx src/scheduled-reports.test.jsx src/profile.test.jsx` → **18 tests, OK** across 3 files
- `npm run lint` → clean (only pre-existing warnings, no errors)
- `npm run build` → succeeds

## Remaining product gaps
- Real SMTP delivery verification against a production-like provider (not claimed; locmem backend used in tests)
- Notification UI consistency pass (dedupe wording, entity links, filters)
- Configurable SMTP email settings in-app (per-user/category opt-out is configurable; SMTP itself remains environment-variable configured)
- No deployment performed

## Safety constraints observed
- All uncommitted work preserved; nothing staged, committed, pushed, reset, cleaned, or discarded
- No database resets; no migrations deleted; no new migrations needed
- No credentials invented; external email delivery not claimed verified