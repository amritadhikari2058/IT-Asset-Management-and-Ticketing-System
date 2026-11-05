# Email intake, notifications, and background processing (Phase 7–8)

Operational reference for the email-to-ticket pipeline, outbound
notifications, and the Celery/Redis scheduled-task layer.

## 1. Inbound email → ticket (email-to-ticket)

- Support intake is **poll-based over IMAP** (provider-agnostic; stdlib
  `imaplib`). No mailbox provider SDK or webhook is required.
- Configuration (environment variables only; never stored in the DB):

  | Variable | Default | Purpose |
  |---|---|---|
  | `INBOUND_MAILBOX_ENABLED` | `true` | Master switch for polling |
  | `INBOUND_MAILBOX_HOST` | *(empty)* | IMAP host (e.g. `mail.example.com`) |
  | `INBOUND_MAILBOX_PORT` | `993` | IMAP port (SSL) |
  | `INBOUND_MAILBOX_USER` / `INBOUND_MAILBOX_PASSWORD` | *(empty)* | Org support mailbox credentials (env-only, never in DB) |
  | `INBOUND_MAILBOX_USE_TLS` | `true` | Use `IMAP4_SSL` vs plain `IMAP4` |
  | `INBOUND_MAILBOX_NAME` | `INBOX` | Folder to poll |
  | `INBOUND_SUPPORT_MAILBOX` | `support@example.com` | Logical support address |
  | `INBOUND_ALLOWED_SENDER_DOMAINS` | *(empty)* | Comma-separated allow-list (e.g. `example.com`) for senders without portal accounts |
  | `INBOUND_MAILBOX_POLL_SECONDS` | `60` | Beat cadence |

- Task: `common.tasks.process_inbound_mailbox`
  (`process_inbound_email_task` is the manual/safe-retry entrypoint).
- Flow: `imaplib` search `UNSEEN` → fetch RFC822 → parse →
  `common.inbound.process_inbound_email` → create ticket / add note.
- **Retry safety:** the `\Seen` flag is only stored after a message is
  processed successfully; failed messages stay `UNSEEN` and are retried on
  the next poll (task is idempotent per `Message-ID` via `common.EmailProcessing`).

## 2. Ingestion rules (security / privacy)

- Eligible senders: known employee email (`accounts.User.email`) or an
  address on `INBOUND_ALLOWED_SENDER_DOMAINS`.
- Unknown senders → recorded `failed` (no ticket created).
- Replies resolved via `In-Reply-To` **or** subject ticket ref (`#42`).
  Sender-supplied ticket IDs are never trusted without access validation:
  a resolved reply requires the sender to be an eligible employee; staff
  replies become **internal** notes (never emailed out); requester replies
  become requester-visible notes + notification.
- Attachments go through the same policy as API uploads
  (`ATTACHMENT_ALLOWED_EXTENSIONS`, `ATTACHMENT_MAX_SIZE_MB`,
  executable blocking) before storage.
- Malformed / unsupported messages are recorded `failed` with a generic
  error summary (no credentials / contents logged).

## 3. Outgoing notifications

- All ticket mail goes through `accounts.email_utils.send_ticket_notification`
  with a cache-based dedup key (`email_sent:{sha256(ticket|subject|to)[:32]}`,
  TTL `EMAIL_DEDUP_TTL_SECONDS`, default 3600) — suppresses duplicate
  delivery from retried events.
- Event emails: creation confirmation (requester), assignment (assignee),
  status change (requester), requester replies (reply receipt), SLA
  approaching/breached, maintenance reminders.
- Recipient preference `User.receive_ticket_emails` is honored (opt-out);
  in-app notifications remain unconditional.
- Delivery failures are caught and logged without credentials or message
  bodies; they never break the ticket flow.

## 4. Celery + Redis background processing

- Celery app: `backend/config/celery.py` (`it_asset_ticketing`), configured
  from `config.settings` via `CELERY_*` namespace.
- Broker / result backend: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
  (default `redis://localhost:6379/0`).
- Retry policy: `CELERY_TASK_MAX_RETRIES` (3) / `CELERY_TASK_RETRY_BACKOFF`
  (60 s); per-task overrides on the inbound task (max 3 / backoff 60) and
  SLA/maintenance tasks (max 2 / backoff 120).
- Time limits: `CELERY_TASK_TIME_LIMIT` (300 s; soft 270 s).
- Worker concurrency: `CELERY_CONCURRENCY` (default 4).
- Task health: every task records an outcome in
  `common.BackgroundTaskRun` (task name, status, success, error summary,
  payload, timings).

### Tasks

| Task | Schedule | Purpose |
|---|---|---|
| `common.tasks.process_inbound_mailbox` | every 60 s | Poll support mailbox, ingest unseen mail |
| `tickets.tasks.check_sla_escalations` | every 300 s | SLA approach/breach notifications |
| `common.tasks.run_scheduled_reports` | every 300 s | Render and deliver scheduled reports |
| `assets.tasks.check_maintenance_reminders` | hourly | Before-due / overdue maintenance reminders |

### Run locally (development)

```bash
# terminal 1
celery -A config.celery worker --loglevel=info --concurrency=4

# terminal 2
celery -A config.celery beat --loglevel=info
```

(Or via `python -m celery -A config.celery ...`.) Redis must be running
locally (`redis-server`), or set `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`
and `CACHE_LOCATION` to point at a managed Redis.

### Production notes

- Run `celery -A config.celery worker -E` (or your orchestrator's worker
  image) and a separate `celery -A config.celery beat` process.
- Beat + worker may run in separate containers/instances; scheduled tasks
  are idempotent (SLAEscalation / MaintenanceReminder get-or-create guards,
  email dedup cache) so multiple beat instances / worker retries cannot
  duplicate notifications.
- Set `CELERY_TASK_MAX_RETRIES`, `CELERY_TASK_RETRY_BACKOFF`,
  `CELERY_TASK_TIME_LIMIT`, `CELERY_CONCURRENCY`, `CELERY_BROKER_URL`,
  `CELERY_RESULT_BACKEND`, and `CACHE_LOCATION` (Redis) via environment.

## 5. Operational visibility

- `GET /api/common/operations/status/` (IT staff / admin only) returns:
  - `email`: `last_successful_processing_at`, `pending`, `failed`,
    `processed_today`, `total` (`common.EmailProcessing`).
  - `tasks`: `celery_healthy` (broker ping) + last 20 `BackgroundTaskRun`
    outcomes.
  - `inbound`: polled mailbox snapshot (`enabled`, `mailbox`,
    `support_mailbox`, `poll_seconds`).

## 6. Failure handling summary

- Inbound: failures → `EmailProcessing.status=failed` (retryable, message
  stays `UNSEEN`); task retries with backoff via Celery; `BackgroundTaskRun`
  records the outcome.
- Outbound: failures never raise; logged (no secrets/bodies); retried task
  attempts are deduped by cache key.
- Ops: monitor `operations/status/` + task runs; simple status page is
  sufficient for Phase 8 scope.

## Verification

- `python manage.py test common.test_phase7` — email ingestion, dedup,
  attachments, replies, ops status, task health, outbound dedup (12 tests).
- Regression suites: `python manage.py test tickets accounts common assets`.

## Safe diagnostics

### Outbound email diagnostic

Configuration-only (no mail sent):

```bash
python manage.py test_email_delivery --dry-run
```

Explicit real-send (requires both `--to` and `--send`):

```bash
python manage.py test_email_delivery --to ops@example.com --send
```

Never sends unless `--send` is explicitly supplied alongside `--to`.
Credentials are never printed. Exit codes: 0 = accepted by backend,
2 = missing/invalid recipient, 3 = missing sender, 4 = send failure.

### Inbound email diagnostic

Configuration check:

```bash
python manage.py check_inbound_email
```

Optional read-only live connectivity (IMAP SELECT only, no mutation):

```bash
python manage.py check_inbound_email --connect
```

### Parser security tests

Run the inbound parser security suite (no live IMAP):

```bash
python manage.py test common.test_inbound_parser
```

Covers: duplicate/missing/malformed Message-ID, missing/malformed sender,
unknown/inactive sender, missing subject, plain-text/HTML-only/multipart
bodies, malformed MIME, body and attachment size limits, blocked and
path-traversal filenames, Unicode/duplicate/empty attachments, idempotent
reprocessing, and EmailProcessing success/failure records.

## Attachment policy

Inbound attachments go through `common.inbound.validate_inbound_attachment`
and share the API upload policy:

| Setting | Default | Purpose |
|---|---|---|
| `ATTACHMENT_ALLOWED_EXTENSIONS` | `pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx` | Allowed extensions |
| `ATTACHMENT_MAX_SIZE_MB` | `10` | Per-file size cap |

Executable extensions (`exe`, `bat`, `cmd`, `sh`, `ps1`, `msi`) and
executable MIME types are blocked regardless of extension list.
