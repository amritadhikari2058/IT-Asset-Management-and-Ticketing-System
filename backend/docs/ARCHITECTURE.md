# System Architecture

## Overview

The IT Ticketing and Asset Management System is a monolithic Django 6 +
Django REST Framework backend with a React (Vite) frontend. It is designed
for a single organizational deployment with role-based access control
(System Admin, IT Manager, IT Support, Employee).

## Components

| Component | Technology | Responsibility |
|-----------|-----------|----------------|
| Backend API | Django 6 + DRF | Business logic, auth, permissions, serialization |
| Frontend | React + Vite | SPA consumed via the REST API |
| Database | PostgreSQL (prod) / SQLite (dev) | Application data, soft-delete, triggers |
| Cache / broker | Redis 7 | Celery broker, result backend, Django cache |
| Background jobs | Celery worker + beat | SLA escalations, maintenance reminders, email intake |
| Object storage | S3-compatible (prod) / local (dev) | Private attachments, employee photos |
| Reverse proxy | Nginx / Caddy | TLS termination, static/media, API proxy |
| SMTP | Any provider | Outbound email (verification, reset, SLA alerts) |

## Data model highlights

- `accounts.User` — email-login users with `role` (system_admin /
  it_manager / it_support / employee), `home_department`,
  `can_create_tickets`, soft-delete.
- `tickets.Ticket` — tickets with SLA due date, priority, status,
  requester, assignee, department, notes, attachments, history.
- `assets.Asset` — assets with serial number (unique), assignment,
  category, department, status, maintenance, disposal.
- `common.Notification` — in-app notifications, soft-delete.
- `common.BackgroundTaskRun` — Celery task outcome tracking.
- `common.AuditLog` — append-only audit trail (actor, action, entity).

## Security boundaries

- All object-level access is enforced in the backend (frontend hiding is
  UX only). Employees see only their own + home-department tickets/assets
  (IDOR protection).
- Attachments are stored with uuid filenames; downloads are proxied
  through permission-checked endpoints — never exposed as public URLs.
- File uploads are validated for extension, size, and executable content
  type.
- Refresh tokens are blacklisted on logout (`token_blacklist`).
- Token obtain/refresh and password-reset endpoints are rate-limited.
- Cookies default to Secure when `DEBUG=False`.

## Request flow

1. Client authenticates via JWT (access + refresh tokens).
2. API request hits Django viewset → permission check → object-level
   visibility filter → serializer validation → business logic.
3. Writes create `AuditLog` rows and `Notification` rows inline (no
   background worker required for correctness).
4. Celery beat fires periodic tasks (SLA, maintenance, email intake);
   outcomes recorded in `BackgroundTaskRun`.

## Deployment topology (production)

```
[Internet] -> [Nginx/Caddy: TLS] -> [Gunicorn: Django API]
                                    -> [React static files]
[Gunicorn] <-> [PostgreSQL]
[Celery worker] <-> [Redis] <-> [Celery beat]
[Nginx] <-> [S3-compatible object storage (private)]
[Gunicorn] -> [SMTP provider]
```

## Trust boundaries

- The backend trusts `X-Forwarded-Proto`/`X-Forwarded-For` only when
  behind a configured reverse proxy (USE_X_FORWARDED_HOST / SECURE_PROXY
  settings as needed).
- The frontend is served from the same origin or a CORS-allowed origin
  only — no wildcard CORS in production.
- S3 objects are private (`AWS_DEFAULT_ACL=None`); access is mediated by
  the application.
