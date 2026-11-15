# Privacy Erasure and Data Lifecycle Governance

## Purpose

This document describes the two-person-approval privacy-erasure workflow and
the data-retention governance added in Phase 25.

**Important:** These controls are operational safeguards. They do **not**
independently establish GDPR or any other regulatory compliance.

## Privacy-erasure lifecycle

A request flows through these states, enforced in the backend:

```
create
  -> pending_review  (awaiting independent review)
       -> approve (by a different System Admin) -> approved
       -> reject (reason required)               -> rejected
       -> cancel                                  -> cancelled
  approved
       -> execute -> execution_pending -> executing -> completed / failed
       -> cancel                                         -> cancelled
  execution_pending / executing -> completed / failed
```

### Rules (backend-enforced)

- **Creation**: System Admin only. Requires `entity_type`, `object_id`,
  `scope`, `reason`, and `confirm` (must equal `object_id`). The target must
  exist; only `accounts.User` is automated.
- **Independent review**: A second System Admin (not the requester) must
  approve or reject. Self-approval / self-rejection is rejected with 409.
- **Rejection** requires a non-blank reason.
- **Execution** requires an `approved` request, a matching scope, explicit
  `confirm`, and a System Admin executor. It runs in a transaction and is
  idempotent (re-executing a completed request is a success, not an error).
- **Scope/reason changes** on an approved request invalidate the approval
  (back to `pending_review`, reviewer cleared).
- **Audit**: creation, approval, rejection, execution, and cancellation are
  all written to `AuditLog` with reviewer/executor identity. PII is never
  logged (IDs + scope only).

### Endpoints

All under `/api/common/privacy-erasures/`, `IsSystemAdmin` only:

- `POST` create → `pending_review`
- `GET /<id>/` detail (incl. dependency/retention analysis + audit history)
- `POST /<id>/approve/` `{decision, reason}`
- `POST /<id>/reject/` `{decision: "reject", reason}`
- `POST /<id>/execute/` `{confirm}`
- `POST /<id>/cancel/` `{reason}`
- `PATCH|PUT /<id>/` update `scope`/`reason` (invalidates approval if approved)
- `GET /<id>/dependency_preview/`

## Data retention policies

Configurable policies for operational data categories:

- security events (AuditLog) — **never auto-deleted**
- notifications (soft-delete old read ones; unread preserved)
- background task runs (soft-delete finished ones; running preserved)
- temporary import reports / expired temporary records / other — manual
  review only (no automated handler)

### Rules

- `AuditLog` (security events) is excluded from every generic retention
  operation.
- Execution re-validates eligibility inside a transaction.
- Soft-delete is respected; running task runs and unread notifications are
  preserved.
- Per-category failure isolation: one category's failure does not corrupt
  unrelated records.
- Results recorded in `DataRetentionExecution`.

### Endpoints

All under `/api/common/retention-policies/` and `/api/common/retention-executions/`,
`IsSystemAdmin` only:

- `GET|POST /retention-policies/` list / create
- `GET|PATCH|PUT|DELETE /retention-policies/<id>/`
- `GET /retention-policies/<id>/preview/` — eligible / excluded without mutating
- `POST /retention-policies/<id>/execute/` — execute (revalidates first)
- `GET /retention-executions/` — execution history

## Background processing

- `common.tasks.evaluate_retention_policies` (beat, hourly): finds due
  enabled policies and dispatches `execute_retention_policy` per policy.
- `common.tasks.execute_retention_policy`: independently re-verifies the
  policy is enabled and executable before mutating, so a queued task can
  never execute a disabled policy outside its window.
- Beat entry: `evaluate-retention-policies` every 3600 s.

Redis / workers / beat are not assumed operational in production without
actual deployment verification.

## Operational procedures

- **Creating a request**: POST with `confirm` equal to `object_id`; the
  request lands in `pending_review`.
- **Reviewing**: a different System Admin opens the request detail and
  approves (with optional reason) or rejects (reason required).
- **Executing**: only after independent approval; confirm the object ID;
  the target's PII is anonymized and history preserved.
- **Reviewing retention**: preview before executing; review exclusion
  reasons; then execute.
- **Failed executions**: check `DataRetentionExecution` for `error_summary`
  and re-run or adjust the policy.

## Frontend

- `#/privacy` — dashboard (KPI counts by status) + request list
- `#/privacy/requests/new` — create request
- `#/privacy/requests/<id>` — detail, dependency analysis, approve/reject/
  execute/cancel
- `#/retention` — policy list, create/edit, enable/disable, preview,
  execute, delete
- `#/retention/executions` — execution history

Navigation entries are shown to System Admin only.
