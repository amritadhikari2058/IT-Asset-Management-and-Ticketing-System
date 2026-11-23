# IT Service Desk — Frontend (React + Vite)

React SPA for the IT Ticketing and Asset Management System backend (Django 6 +
DRF). Auth is JWT (access + refresh); the SPA talks to `VITE_API_BASE_URL`
(default `http://127.0.0.1:8000/api`).

## Token storage (security note)

By default, access + refresh tokens are stored in `localStorage` (`src/auth.jsx`
and `src/api.js`). This is convenient but means any same-origin XSS can read the
tokens. The backend mitigates session theft via short-lived access tokens (1h),
blacklisted refresh tokens on logout, rate-limited auth endpoints, and Secure
cookies when `DEBUG=False`, but the tokens themselves are still script-readable
on the frontend.

There is an **opt-in** backend path that hardens the refresh token specifically:
set `JWT_REFRESH_COOKIE_ENABLED=true` (and optionally `JWT_REFRESH_COOKIE_NAME`)
and the refresh endpoint returns the refresh token as an `httpOnly` / `secure` /
`sameSite=Lax` cookie and omits it from the JSON body. In that mode the frontend
stops storing the refresh token in `localStorage` and refreshes via the cookie
(the browser sends it automatically), so the refresh token is no longer directly
readable by script. Caveats: (1) the access token is still kept in memory +
`localStorage` for the page-reload boot, and is still script-readable; (2) in
cookie mode the client cannot delete the httpOnly refresh cookie itself, so logout
relies on the backend clearing the cookie (the backend logout endpoint already
does this); (3) until MFA is enabled, a stolen access token still grants a
full short-lived session.

Recommended end state (not fully implemented today): httpOnly refresh cookie +
short-lived in-memory access token (no `localStorage` access either) + MFA.
Until then, XSS prevention and a strict Content Security Policy are the primary
mitigating controls. See `backend/docs/KNOWN_LIMITATIONS.md` (Authentication /
authorization) for the backend-side summary.

## MFA (future work)

Multi-factor authentication is not implemented. If enabled, the intended path
is time-based one-time passwords (TOTP) enrolled per user, with login
returning a `pending_mfa` outcome and a follow-up challenge endpoint so
password-only clients are unaffected until MFA is opted in.

## Developing

```bash
cd frontend
npm install
npm run dev     # Vite dev server with HMR
npm run build  # static files for the backend to serve
npm run lint    # oxlint
npm test        # vitest
```

## Architecture / deployment

See `backend/docs/ARCHITECTURE.md` and `backend/docs/KNOWN_LIMITATIONS.md`.
No Kubernetes manifests, Helm charts, or Dockerfiles are provided; operators
provision VMs/containers and process management themselves.
