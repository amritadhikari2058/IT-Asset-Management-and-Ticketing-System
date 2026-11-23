# Security audit — IT Service Desk / Asset & Procurement Management

**Scope:** backend (Django 6 + DRF + SimpleJWT) and frontend (React + Vite) as read from the repository.
**Method:** each finding below is grounded in a file/setting/path that was read during the audit; no findings were inferred from memory.
**Status:** findings are ordered HIGH → MEDIUM → LOW/robustness. Items already remediated this session are recorded in the Remediation section at the end.

---

## Findings

### HIGH

#### H1. Auth endpoints are globally throttled but not account-scoped (brute-force / account-spam surface)

**Where:** `backend/config/settings.py` (`DEFAULT_THROTTLE_RATES.auth = 20/minute`), `backend/common/throttling.py` (`AuthRateThrottle(scope='auth')` subclass of `AnonRateThrottle`), `backend/accounts/auth_views.py` (`password_reset_request`, `password_reset_confirm`, `verification_request`, `change_password`, `logout` all decorated with `@throttle_classes([AuthRateThrottle])`).

**What it means:** The auth flow is limited at the *transport* level, but password-reset, verification, and password-change are not rate-limited per *account*. An attacker can target a single account across many IPs or anonymous identities and stay under the global `auth` throttle while still hamming one victim.

Present behavior:
- `password_reset_request` returns the same generic message for existing/non-existing addresses, which is good for enumeration resistance, but there is no per-address cooldown.
- `verification_request` can be called repeatedly by a session that already has credentials.
- `change_password` requires the current password, but repeated wrong-current-password attempts were not account-scoped.

**Impact:** Credential-stuffing and account-spam are the most likely abuse patterns against a public login/reset surface. Global throttling slows bulk traffic; it does not stop a focused attack on one account.

**Remediation status:** Remediated this session (see Remediation R1).

---

#### H2. Production CSP still allows `unsafe-inline` unconditionally

**Where:** `backend/config/settings.py`, CSP block: `CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'")`, `CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")`.

**What it means:** The CSP is the main remaining mitigation for the localStorage token-storage posture. Keeping `unsafe-inline` on for both script and style materially weakens that mitigation: an XSS that can inject inline script/style is not contained by the policy.

**Impact:** Medium. The policy still constrains external script/source origins and blocks plugins, but the inline allowance is the part that actually stops the most likely same-origin XSS. Until `unsafe-inline` is removed for production, the CSP is a partial defense.

**Remediation status:** Remediated this session (see Remediation R2). Must still be smoke-tested against the built production frontend before enabling in production.

---

#### H3. Several production-safe header defaults were not set, so the security warnings corresponded to empty opt-ins

**Where:** `backend/config/settings.py` and Django's `SecurityMiddleware` (in `MIDDLEWARE`):
- `SECURE_HSTS_SECONDS` is 0 by default (no HSTS).
- `SECURE_HSTS_INCLUDE_SUBDOMAINS` was not set.
- `X_FRAME_OPTIONS` was not explicitly set (Django default is `DENY`, but it was not pinned in config).
- `SECURE_CONTENT_TYPE_NOSNIFF` was not set globally (nosniff was applied per-response on file downloads only).

**What it means:** A fresh production deploy could boot without HSTS, without subdomain coverage, and without a global nosniff header unless the operator explicitly sets each env var. The validator already warned about these, but the defaults did not harden a new deploy out of the box.

**Impact:** Medium. HSTS, framing, and MIME sniffing are basic production hardening; leaving them as opt-ins is a common “works in dev, soft in prod” gap.

**Remediation status:** Remediated this session (see Remediation R3).

---

#### H4. Refresh-token cookie path is opt-in and applies only to refresh; login still returns both tokens in JSON, and the access token still lives in localStorage

**Where:** `backend/config/settings.py` (`JWT_REFRESH_COOKIE_ENABLED`, `JWT_REFRESH_COOKIE_NAME`), `backend/common/views.py` (`TokenRefreshViewWithOptionalRefreshCookie`), `backend/accounts/auth_views.py` (`logout` reads refresh from body or cookie), frontend `src/api.js` / `src/auth.jsx` (token storage / refresh path).

**What it means:** The refresh-token cookie hardening reduces the refresh token's exposure, but:
- it is opt-in and currently scoped to the refresh endpoint;
- login still returns both tokens in JSON; and
- the access token still lives in localStorage in the current frontend path.

**Impact:** Medium. The refresh-token hardening is good, but the biggest remaining token-exposure risk is the access token in localStorage combined with the still-`unsafe-inline`-friendly CSP (H2). This is why H2 matters more than it first appears.

**Remediation status:** Not changed this session (already opt-in). Remaining open item — see Remediation section.

---

### MEDIUM

#### M1. Email credential and inbound-mailbox credential handling is env-driven and fail-soft, which is fine, but the production default path still boots with a console email backend + no IMAP host unless set

**Where:** `backend/config/settings.py` (`EMAIL_BACKEND`, `EMAIL_HOST_*`, `INBOUND_MAILBOX_*`), `backend/common/management/commands/validate_production_config.py` (email + inbound checks).

**What it means:** The app is provider-agnostic and credential-friendly (env-driven, not committed defaults in production), but a production deploy that does not set SMTP/IMAP will run with a console email backend and enabled-but-unconfigured inbound polling. That is an operational failure mode more than a security bug, but it can mask “email isn’t actually sending” as “email works” during rollout.

**Impact:** Medium in the “verification before go-live” sense; low as a confidentiality/integrity bug.

**Remediation status:** Not changed this session. Covered by the recommended live-service verification step.

---

#### M2. Admin is present and soft-delete-aware; sensitive models are protected, but the admin surface is broad and depends on the operator keeping admin authentication strong

**Where:** `backend/common/admin_config.py`, per-app `admin.py` files, `backend/config/urls.py` (`admin/`), `backend/config/settings.py` (admin in `INSTALLED_APPS`).

**What it means:** Django admin is enabled and extensively customized (soft-delete-aware, restore actions, read-only audit log, mostly read-only history/outbox admins). Several sensitive models are protected (AuditLog has no add/delete; multiple history/outbox/invoice admins are read-only). This is good. The residual risk is operational: admin access is a high-value target and depends on strong admin authentication, restricted network exposure, and good superuser hygiene.

**Impact:** Medium, mostly operational.

**Remediation status:** Not changed this session. No defect found; recommend restricting admin network exposure and treating admin auth as a first-class rollout item.

---

#### M3. CORS defaults allow localhost dev origins; production must override them

**Where:** `backend/config/settings.py` (`CORS_ALLOWED_ORIGINS` defaults to `http://localhost:5173,http://127.0.0.1:5173`; `CORS_ALLOW_CREDENTIALS=True`), `backend/common/management/commands/validate_production_config.py` (CORS wildcard/empty checks).

**What it means:** The defaults are reasonable for local dev. In production, the deploy must set `CORS_ALLOWED_ORIGINS` to the real frontend origin(s) and clear the dev defaults. The validator checks for wildcard/empty origins, so a misconfigured production deploy should be caught.

**Impact:** Medium if an operator leaves dev defaults in production behind a misconfigured proxy; low if the deployment docs/env are followed.

**Remediation status:** Not changed this session. The validator already enforces this.

---

#### M4. CSRF cookie and session cookie are secure-by-default in production, but only if `DEBUG=false`

**Where:** `backend/config/settings.py` (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` default to secure when `DEBUG=false`).

**What it means:** Good: production (DEBUG=false) defaults cookies to secure. The residual risk is the same as H3 — an operator must actually deploy with `DEBUG=false` and HTTPS, or the secure-cookie defaults do not take effect.

**Impact:** Medium in the rollout sense.

**Remediation status:** Not changed this session. Already correct by design; reinforced by H3 defaults + validator.

---

#### M5. Password reset / verification tokens are Django’s default token machinery; password change requires current password

**Where:** `backend/accounts/auth_views.py`, `backend/accounts/email_utils.py`.

**What it means:** Reset/verification use Django’s built-in token flow with generic responses and best-effort email delivery. Password change requires the current password. This is a sound baseline.

**Impact:** Low-medium. No defect found; the main improvement was adding account-scoped cooldowns (H1 / R1).

**Remediation status:** Strengthened this session via R1.

---

### LOW / robustness

#### L1. New cooldown helper initially used `datetime.utcnow()` (deprecated in modern Python)

**Where:** `backend/common/throttling.py` (first version of `account_action_cooldown`).

**What it means:** A deprecation warning under Python 3.14+. Not a security defect, but a robustness/maintenance issue and a warning-noise source in CI/logs.

**Remediation status:** Fixed this session (R4).

---

#### L2. A malformed duplicated `verification_confirm` block was introduced by an earlier edit

**Where:** `backend/accounts/auth_views.py` (a duplicated/mangled `verification_confirm` with a stray decorator + `pass` marker).

**What it means:** Not a live defect once corrected, but it was the kind of artifact that can hide a real regression if left in place. It was cleaned up.

**Remediation status:** Fixed this session (R4).

---

#### L3. `runserver 0:8000` and `start_backend.bat` exist for local dev; production uses gunicorn

**Where:** `start_backend.bat`, `docker-compose.yml`, `Dockerfile`, `backend/config/settings.py` note about `runserver` localhost behavior.

**What it means:** Not a defect: `runserver 0:8.0.0.0:8000` is a dev convenience, and production uses gunicorn behind a proxy. The real exposure is whether production actually deploys with `DEBUG=false`, explicit `ALLOWED_HOSTS`, and a reverse proxy doing TLS. This is an operational posture item, not a code defect.

**Remediation status:** Not changed this session. Reinforced by validator + recommended verification step.

---

#### L4. Outbox/dedup/retention/CMDB/licensing-security subsystems are extensive and mostly well-gates; the main residual is verification, not defects

**Where:** `backend/common/outbox.py`, `backend/common/inbound.py` (`validate_inbound_attachment`), `backend/tickets/serializers.py` (`validate_attachment_file`), `backend/licensing/security.py`, `backend/licensing/views.py` (`reveal`), `backend/cmdb/permissions.py`, `backend/common/models.py` (audit integrity hash), `backend/common/management/commands/audit_integrity_check.py`.

**What it means:** Attachment validation, secret encryption/fail-closed reveal, CMDB role gates, and outbox dedup all appear sound on reading. The residual risks are operational verification (is the encryption key actually configured in prod? does inbound actually ingest? does the outbox actually drain?) rather than obvious code defects.

**Remediation status:** Not changed this session. Covered by recommended verification step.

---

## Remediation applied in this session

### R1. Auth brute-force / account-spam hardening (HIGH → addressed)

**Files changed:**
- `backend/common/throttling.py` — added `account_action_cooldown(key_prefix, window_seconds)` on top of the Django cache backend (timezone-aware UTC; tolerates stale naive cache entries). `AuthRateThrottle` unchanged.
- `backend/accounts/auth_views.py` — wired per-account cooldowns into:
  - `password_reset_request` (60s per email; checked before any side effect so timing is identical for existing/non-existing addresses inside the cooldown);
  - `password_reset_confirm` (60s per email after a successful reset; blocks automated token-reuse attempts);
  - `verification_request` (60s per account; returns 429 when recently sent);
  - `change_password` (60s per account; blocks brute-forcing the current password with a stolen session).

**Verification:** `accounts/tests.py` — 68 passed; `common/tests.py` + `common/role_security_tests.py` + `common/test_monitoring.py` — 151 passed; `common/test_management_commands.py` — 42 passed. No deprecation warnings remain from the new code.

---

### R2. CSP tightened for production + violation reporting (MEDIUM → addressed)

**Files changed:**
- `backend/config/settings.py` — production CSP no longer includes `'unsafe-inline'` for scripts/styles. Inline allowances remain only when `DEBUG=True` (for Vite/HMR/dev tooling). Added optional `CSP_REPORT_URI` env var for best-effort violation reporting.

**Verification (configuration only this session):** `python manage.py validate_production_config --strict` and `python manage.py check --deploy` run cleanly under the local DEBUG/dev config. The production CSP path itself must be smoke-tested against the built frontend before enabling in production.

---

### R3. Production-safe default security headers (MEDIUM → addressed)

**Files changed:**
- `backend/config/settings.py` — added production-safe defaults:
  - `SECURE_HSTS_INCLUDE_SUBDOMAINS=true` when HSTS is configured (false otherwise);
  - `X_FRAME_OPTIONS=DENY` by default (overridable per env);
  - `SECURE_CONTENT_TYPE_NOSNIFF=true` in production / false in DEBUG (already applied per-response on file downloads).

**Verification (configuration only this session):** `validate_production_config --strict` and `check --deploy` now report `X_FRAME_OPTIONS=DENY` as PASS and surface the remaining production-only gaps (ALLOWED_HOSTS, cookie-secure, HSTS seconds, email backend, SQLite) as expected for the local dev configuration. `manage.py check` reports 0 issues.

---

### R4. Robustness / correctness cleanup (LOW → addressed)

- Replaced `datetime.utcnow()` in the cooldown helper with timezone-aware UTC.
- Cleaned up a malformed duplicated `verification_confirm` block in `auth_views.py` and restored a single correct implementation.

---

## Remaining open items (not addressed this session)1.  **Audit-log integrity chain is still opt-in/unverified.** `AUDIT_INTEGRITY_HASH_ENABLED` and `audit_integrity_check` exist but are not run as a deployed gate/readiness signal.
2.  **Email delivery and inbound mailbox are not verified live this session.** Validator checks config, not actual SMTP/IMAP behavior.
3.  **Tightened CSP must be smoke-tested against the built frontend before production.** The policy now drops `unsafe-inline` in production, but the built Vite output was not rendered through it this session.
4.  **Refresh-cookie / access-token posture is still split.** Refresh can go to an httpOnly cookie (opt-in), but the access token still lives in localStorage. CSP hardening (R2) is the mitigator until a full cookie-based access-token path is implemented.
5.  **Rate-limit surface beyond auth was not expanded this session.** Sensitive writes (role/permission changes, bulk import, license secret reveal/rotate, hard-delete) rely on existing permission gates + global throttles.
6.  **Pre-go-live live-service verification step (DEPLOYMENT.md) was not written this session.** Refer to the "Live-service verification (pre-go-live)" section below for the ordered, runnable procedure.

---

## Live-service verification (pre-go-live)

This is the ordered verification step for deployment readiness. It covers every finding in the "Remaining open items" list and every gap the production validator cannot check (actual service reachability, real login + refresh behavior, and the tightened CSP against the built frontend). Run it against a staging or post-deploy environment; record PASS/FAIL for each check.

### 1. Database reachable + migrations current

```bash
cd backend && python manage.py check --database --fail-level ERROR && python manage.py migrate --check --dry-run
```
Expected: `check` exits 0 and `--check --dry-run` reports no unapplied migrations.

### 2. Redis reachable (broker + cache)

```bash
cd backend && python manage.py check_redis --timeout 5 && python manage.py check_celery_config
```
Expected: PING succeeds and Celery broker/config is sane (json serializer, no pickle, `CELERY_TASK_ALWAYS_EAGER=false`).

### 3. Celery worker + beat running

```bash
cd backend && python manage.py check_celery_worker
```
Expected: `inspect ping` returns OK. Verify beat is scheduling the periodic tasks (`check_sla_escalations`, `run_scheduled_reports`, `process_inbound_mailbox`, `check_maintenance_reminders`, `detect_repeated_task_failures`, `detect_missed_scheduled_tasks`).

### 4. SMTP outbound send (real verification + password-reset email)

```bash
cd backend && python manage.py test_email_delivery --to ops@example.com --send
```
Expected: a real verification + password-reset email delivers. This is what the configuration-only check cannot prove.

### 5. IMAP inbound connect (read-only)

```bash
cd backend && python manage.py check_inbound_email --connect
```
Expected: SELECT on the inbox succeeds. This proves inbound polling will actually ingest mail.

### 6. S3 (if used)

```bash
cd backend && python -c "from django.conf import settings; from storages.utils import early_deprecation_check; early_deprecation_check(); print(settings.AWS_STORAGE_BUCKET_NAME)"
```
Expected: bucket resolves with `AWS_DEFAULT_ACL=None` (private objects). If S3 is not in use, mark as N/A.

### 7. Health + readiness probes

```bash
curl -sS http://localhost:8000/health/ && curl -sS http://localhost:8000/ready/
```
Expected: `/health/` is 200; `/ready/` is 200 only when the DB is reachable (`503` otherwise). Behind a TLS proxy, `SECURE_PROXY_SSL_HEADER` must be set so the probe sees TLS.

### 8. Real login + refresh round-trip (JWT + refresh-cookie path)

Using the built frontend against the production API:

1. Log in → confirm the access token is returned (and that the refresh cookie is sent for the refresh path per `JWT_REFRESH_COOKIE_ENABLED`).
2. Call `/api/auth/token/refresh/` (or the cookie endpoint) with the refresh token → confirm a valid new access token. This is the real auth flow, not just configuration.
3. Confirm `logout` blacklists the refresh token when `BLACKLIST_ENABLED=True`.

### 9. CSP check against the built frontend

```bash
cd frontend && npm run build && npx http-server dist -p 4173 -s >/dev/null 2>&1 &
```
Then load the production-built site through a browser with the production CSP active (curl the page headers to confirm `'unsafe-inline'` is absent from `Content-Security-Policy`) and record whether any CSP violations appear in the console/network. Fix any violation; for third-party origins, pin them explicitly rather than re-adding `unsafe-inline`.

### 10. Audit-log integrity chain (readiness gate)

```bash
cd backend && python manage.py audit_integrity_check
```
Expected: the current log chain verifies. If it fails, it should be treated as a deployment gate (not silently ignored).

### 11. Outcome record

Record the PASS/FAIL result for every check above in the deployment runbook. Any FAIL blocks go-live until the underlying gap is closed (this is the live verification that the configuration validator cannot substitute for).

2. After the production build is available, render it through the tightened CSP and fix any violations before enabling the strict policy in production.
3. Decide whether to enable `AUDIT_INTEGRITY_HASH_ENABLED` and add `audit_integrity_check` as a readiness/gate signal.
4. Decide whether to extend per-action cooldowns to other sensitive writes (roles/permissions, bulk import, license secret reveal/rotate, hard-delete).
