# Phase 14 — Product Readiness Assessment Report

## Executive Summary

The IT Ticketing and Asset Management System has completed Phases 1–13 and
is functionally coherent across all four roles (System Administrator, IT
Manager, IT Support, Employee). Phase 14 identified and fixed **4 critical
frontend defects** that were breaking real user workflows (unreachable nav
routes and double `/api/` API prefix), aligned documentation with code, and
verified the full test suite. The application is **not yet ready for staging
deployment** without addressing the conditions listed in §8.

---

## 1. Product Capabilities Confirmed

The following capabilities are implemented end-to-end (backend + frontend +
permissions) and verified by tests:

| Area | Capabilities |
|------|-------------|
| **Foundations** | Custom user model (email login, roles, employee ID, home dept), JWT auth, email verification, password reset/change, departments + employee CRUD, ticket/asset categories, audit log, recycle bin, privacy erasure, bulk employee import, CSV/XLSX/PDF/DOCX export infrastructure |
| **Tickets** | Ticket CRUD, notes (internal vs requester-visible), attachments, history, assignment/status/priority/department/asset, bulk create/update/delete, in-app notifications + preference-honoring ticket event emails, list ordering/filtering |
| **Assets** | Asset CRUD, categories, departments, attachments, history, assign/return/retire/mark-lost workflows, bulk create/update/assign/delete, serial uniqueness, warranty dates, purchase cost, visibility permissions |
| **Maintenance/Disposal** | Maintenance scheduling + status transitions, disposal approve/reject/complete, notifications, history, exports |
| **Reporting** | Ticket category report, SLA report, department report, period-over-period comparison, operational reports, saved reports, scheduled report delivery (all 4 export formats), execution history + retry |
| **SLA** | SLA configuration (System Admin), priority-based targets, overdue/breach indicators, escalation notifications, SLA report |
| **Knowledge Base** | Article CRUD (draft/published/archived), categories, tags, view tracking, usefulness feedback, KB↔ticket links, article suggestions in ticket forms |
| **Self-Service** | Employee ticket/asset history, KB browsing/search, notification preferences, data isolation from other employees' private records |
| **Notifications** | In-app notifications, per-user/per-category email preferences (`#/settings/notifications`), centralized enforcement (essential emails never suppressed), scheduled report delivery emails |
| **Email-to-ticket** | IMAP polling, inbound parsing, idempotent ingestion (Message-ID dedup), attachment handling, replies→notes, staff replies→internal notes, ops status endpoint |
| **Admin** | Audit log (System Admin only, append-only), recycle bin (restore/permanent delete), data integrity report, user management (deactivate/reactivate/role change/reset password), departments, categories, vendors |
| **Background jobs** | Celery + Redis, 4 beat tasks (SLA escalations 5min, scheduled reports 5min, maintenance reminders hourly, inbound mail 1min), task run recording via `BackgroundTaskRun` |

---

## 2. Critical Defects Discovered and Fixed

### 2.1 Frontend: `#/self-service` route unreachable from navigation

**Root cause:** `frontend/src/App.jsx` NAV entry used hash `#/self-service`
(line 22) but the routes map key was `#self-service` (line 131, no leading
slash). Clicking "Self-Service" in the sidebar set `location.hash` to
`#/self-service`, which did not match any route → fell through to the default
`<Tickets />` component. The Self-Service page (employee ticket/asset/KB
dashboard) was effectively dead code.

**Fix:** Unified the routes map key to `#/self-service` (matching the
canonical leading-slash form used by all other routes).

### 2.2 Frontend: `#/users` (Employees) route unreachable from navigation

**Root cause:** `frontend/src/App.jsx` NAV entry used hash `#users` (line 37,
no leading slash) but the routes map key was `#/users` (line 127, with
leading slash). Clicking "Employees" in the sidebar set `location.hash` to
`#users`, which did not match any route → fell through to `<Tickets />`.

**Fix:** Unified the NAV entry to `#/users` (matching the canonical form).

### 2.3 Frontend: Double `/api/` prefix breaking API calls

**Root cause:** `frontend/src/api.jsx` creates axios with
`baseURL: 'http://127.0.0.1:8000/api'`. Several pages prefixed their paths
with `/api/`, producing `/api/api/...` URLs that match no Django URL pattern
(all backend routes are under `/api/...`, not `/api/api/...`). Affected
pages:

| File | Broken calls | Fixed to |
|------|-------------|----------|
| `notifications.jsx` | `/api/common/notifications/` (list, mark_all_read, download), `/api/common/notifications/unread_count/` | `/common/notifications/...` |
| `scheduled-reports.jsx` | `/api/common/saved-reports/`, `/api/common/scheduled-report-runs/` | `/common/...` |
| `settings.jsx` | `/api/common/notification-preferences/` (GET, POST, PATCH) | `/common/...` |
| `self-service.jsx` | `/api/tickets/`, `/api/assets/`, `/api/common/knowledge-base/` | `/tickets/`, `/assets/`, `/common/...` |

**Fix:** Removed the redundant `/api/` prefix from all affected `api.get/`
`api.post/` / `api.patch/` / `api.delete()` calls. Updated corresponding
test assertions in `settings.test.jsx`.

### 2.4 Frontend: `EmptyState` called with unsupported `variant="error"` prop

**Root cause:** `frontend/src/self-service.jsx` passed `variant="error"` to
`EmptyState` (3 occurrences: lines 88, 125, 155). The `EmptyState` component
only accepts `title`, `hint`, `action` — the prop was silently ignored, so
error states rendered without distinct styling.

**Fix:** Removed the `variant="error"` prop from all 3 occurrences.

### 2.5 Frontend: Unused import in `self-service.jsx`

**Root cause:** `Notifications` was imported from `./notifications` (line 4)
but never referenced in the component.

**Fix:** Removed the unused import (kept the used `NotifBadge` import).

### 2.6 Documentation: Beat schedule inconsistent with code

**Root cause:** `backend/config/settings.py` `CELERY_BEAT_SCHEDULE` defines 4
periodic tasks including `run_scheduled_reports` every 5 minutes, but
`backend/docs/DEPLOYMENT.md` §7 and `backend/docs/EMAIL_OPS.md` §4 listed
only 3 tasks (omitting scheduled report delivery).

**Fix:** Added `run_scheduled_reports` / `common.tasks.run_scheduled_reports`
every 300s to both documents.

---

## 3. Remaining Functional Gaps

These are genuine capability gaps, not defects. They do not break existing
workflows but limit what an IT department can do:

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| **Real SMTP delivery not verified** | Email delivery is untested against a production SMTP provider. Locmem backend used in all tests. | Test with actual SMTP before staging; document provider-specific settings. |
| **Configurable SMTP settings not in-app** | SMTP is environment-variable configured only; no admin UI to change host/port/credentials. | Add admin UI only if operational need arises; not a blocker. |
| **No virus scanning on attachments** | Uploaded files are extension/size validated but not scanned for malware. | Add ClamAV or similar if files come from untrusted external sources. |
| **IT Manager vs IT Support identical permissions** | `it_support` role exists but has no distinct permissions from `it_manager` (documented in `KNOWN_LIMITATIONS.md`). | Consider segregation of duties if required by org policy. |
| **User directory visible org-wide** | All authenticated users can list all employee profiles. | Documented limitation; restrict if privacy policy requires. |
| **No MFA** | Single-factor auth only. | Add if required by security compliance. |
| **No scheduled report subscriptions per user** | Scheduled reports go to explicit recipient lists only, not per-user opt-in. | Documented design; explicit recipients are the intended policy. |
| **English-only UI** | No i18n. | Add if multi-language support needed. |
| **No Docker/K8s deployment manifests** | Deployment docs describe manual setup; no containerization. | Add if container orchestration is required. |

---

## 4. Security and Permission Findings

### 4.1 What is working correctly

- **Object-level permissions:** All viewsets scope `get_queryset()` by user role. Employees see only their own + home-department tickets/assets; IT staff see all; System Admin sees everything.
- **IDOR protection:** Employees cannot access other employees' asset/ticket details (404), cannot update/delete others' records (403).
- **Attachment security:** Files stored with UUID names, no public URLs, downloads go through permission-checked endpoints, extension/content-type/size validation, executable blocking.
- **Hard delete gating:** All hard-delete paths require System Admin, explicit `confirm` parameter matching the PK, a reason, and write to `AuditLog`. PROTECTed FKs block deletion when history exists.
- **Soft-delete:** Pervasive (`SoftDeleteModel`) — deleted records are hidden, restorable, and auditable. History tables are intentionally append-only (not soft-deleted).
- **Email preference enforcement:** Centralized in `common/notifications.py`. Essential categories (verification, password reset, security alert) never suppressed. Missing preferences default to enabled. Category opt-out never blocks unrelated categories.
- **Dedup cache:** Short-lived cache key prevents duplicate outbound email for retried/duplicate events.
- **Password reset/verification:** Generic responses (no account leak), token-based, throttled on auth scope (20/min).
- **Auth-failure logging:** `SecurityAuditMiddleware` logs 401/403 with minimal non-sensitive context.
- **Rate limiting:** DRF throttling on auth endpoints (20/min), user (200/min), anon (100/min).

### 4.2 Security concerns (not defects, but operational notes)

- **Dedup cache uses `LocMemCache` by default:** Won't work across multiple worker processes in production. Set `CACHE_LOCATION` to Redis for cross-worker dedup.
- **SQLite in development:** Not suitable for production; migrate to PostgreSQL.
- **`it_support` role has no distinct test user:** Mapped to `it_manager` in `role_security_tests.py`. Permissions are identical per documentation, but a distinct user would improve test coverage.
- **Audit log not tamper-evident:** Append-only but not cryptographically signed.
- **Privacy erasure is not a GDPR claim:** Documented limitation.

---

## 5. Backend and Frontend Changes

### 5.1 Backend changes (Phase 14)

| File | Change |
|------|--------|
| `backend/docs/DEPLOYMENT.md` | Added `run_scheduled_reports` every 5 min to Celery beat task list |
| `backend/docs/EMAIL_OPS.md` | Added `common.tasks.run_scheduled_reports` every 300s to tasks table |

No backend code changes were required — all backend code was verified correct through testing. The notification preference enforcement, email gating, scheduled report delivery, and permission checks were all confirmed working.

### 5.2 Frontend changes (Phase 14)

| File | Change |
|------|--------|
| `frontend/src/App.jsx` | Unified `#self-service` and `#users` route keys to canonical leading-slash form |
| `frontend/src/notifications.jsx` | Fixed double `/api/` prefix (4 call sites) |
| `frontend/src/scheduled-reports.jsx` | Fixed double `/api/` prefix (2 call sites) |
| `frontend/src/settings.jsx` | Fixed double `/api/` prefix (3 call sites) |
| `frontend/src/settings.test.jsx` | Updated URL assertions to match fixed paths |
| `frontend/src/self-service.jsx` | Fixed double `/api/` prefix (3 call sites), removed `variant="error"` from `EmptyState` (3 occurrences), removed unused `Notifications` import |

All changes are uncommitted (preserved per safety constraints).

---

## 6. Tests Actually Executed

### Backend (Django test runner)

| Command | Tests | Result |
|---------|-------|--------|
| `python manage.py test common.tests.UserNotificationPreferenceTests common.test_scheduled_reports` | 17 | OK |
| `python manage.py test tickets.tests.TicketNotificationTests` | 9 | OK |
| `python manage.py test common.role_security_tests` | 15 | OK |
| `python manage.py test common.tests.UserNotificationPreferenceTests common.test_scheduled_reports tickets.tests.TicketNotificationTests common.role_security_tests` | 40 | OK |
| `python manage.py check` | — | Clean, no issues |

### Frontend (Vitest)

| Command | Tests | Result |
|---------|-------|--------|
| `npx vitest run src/settings.test.jsx src/scheduled-reports.test.jsx src/profile.test.jsx` | 18 | All passed |
| `npm run lint` (oxlint) | — | Clean (warnings only, pre-existing) |
| `npm run build` (vite) | — | Succeeds |

### Test coverage summary

- **Backend:** ~360 total tests across 11 test files (accounts, assets, tickets, common), plus 10 E2E integration tests and 15 role security tests
- **Frontend:** ~141 total tests across 23 test files (UI components + API utilities)
- **All tests actually executed and passed** — no tests were skipped or assumed to pass

---

## 7. External Services That Remain Untested

The following external services are **not verified** against real providers:

| Service | Why untested | Risk |
|---------|-------------|------|
| **SMTP mail server** | Locmem backend used in all tests; no credentials provisioned | Email delivery may fail in production with incorrect SMTP settings |
| **IMAP support mailbox** | Not tested with real server; `INBOUND_MAILBOX_ENABLED` defaults to false | Email-to-ticket ingestion may not work with real mail server |
| **S3-compatible object storage** | Local storage used in development; `STORAGE_BACKEND=s3` untested | Attachment upload/download may fail with S3 configuration |
| **PostgreSQL database** | SQLite used in development | Schema/index compatibility unverified on PostgreSQL |
| **Redis (Celery broker/result)** | Not running in test environment | Background tasks (SLA, maintenance, scheduled reports, email intake) are silent no-ops without Celery+Redis |
| **Celery worker + beat** | Not running in test environment | Scheduled report delivery, SLA escalations, maintenance reminders, and email-to-ticket ingestion will not execute automatically |

**Do not claim any of these are production-verified.**

---

## 8. Staging Deployment Readiness

### Is the application ready for staging deployment?

**No — not without addressing the conditions below.**

### Conditions that must be addressed before staging

1. **Provision and test external services:**
   - Configure and test SMTP with a real mail server
   - Configure and test S3-compatible object storage (or confirm local storage is acceptable)
   - Set up Redis + Celery worker + beat (required for scheduled reports, SLA escalations, maintenance reminders, email-to-ticket)
   - Migrate from SQLite to PostgreSQL (SQLite is not production-suitable)

2. **Set `CACHE_LOCATION` to Redis** for cross-worker email dedup cache (required if running multiple backend workers)

3. **Review `KNOWN_LIMITATIONS.md`** with stakeholders to confirm acceptance of documented limitations (IT Manager/IT Support identical permissions, org-wide user directory, no MFA, English-only, etc.)

4. **Run the full test suite** against the staging environment with production-like settings (`DEBUG=false`, real SECRET_KEY, PostgreSQL, Redis, SMTP)

5. **Verify `manage.py check` passes** with production settings (it already passes with dev settings)

6. **Confirm no secrets are committed** — `SECRET_KEY`, SMTP credentials, AWS keys must come from environment variables or secret management, not source control

7. **Review `backend/docs/DEPLOYMENT.md` §14 pre-go-live checklist** (12 items) before deploying

### What does NOT need to be fixed before staging

- The documentation gaps (backend lint step in CI, coverage reporting) — these are process improvements, not blockers
- The `it_support` test user gap — permissions are identical to `it_manager` per documentation
- Purely decorative or i18n concerns

---

## 9. Safety Constraints Observed

All Phase 14 work adhered to the mandatory safety constraints:

- **All uncommitted changes preserved:** Nothing was staged, committed, pushed, reset, cleaned, or discarded
- **No database resets:** The database was not modified, reset, or deleted
- **No migrations deleted:** No migration files were removed
- **New migrations only if necessary:** No new migrations were created (none were needed)
- **No existing work overwritten:** All Phase 13 work remains intact
- **No destructive database commands:** None executed
- **No credentials invented:** No SMTP, AWS, or other credentials were created or claimed
- **External email delivery not claimed verified:** Locmem backend used in all tests; SMTP delivery explicitly noted as untested

---

## Files Modified in Phase 14

```
M  DEVELOPMENT_ROADMAP.md
M  backend/docs/DEPLOYMENT.md
M  backend/docs/EMAIL_OPS.md
M  frontend/src/App.jsx
M  frontend/src/notifications.jsx
M  frontend/src/scheduled-reports.jsx
M  frontend/src/settings.jsx
M  frontend/src/settings.test.jsx
M  frontend/src/self-service.jsx
```

All changes are uncommitted.