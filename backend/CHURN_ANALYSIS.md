# Codebase Churn Analysis

## Project Overview
A Django IT Service Management system with 28 installed apps (including Django core and 3rd-party).

## Model Counts by App
| App | Models | URL Patterns | Description |
|-----|--------|--------------|-------------|
| **common** | 17 | 9 | Core infrastructure: soft-delete, audit log, notifications, privacy erasure, retention policies, health checks, operational errors/alerts/incidents |
| **accounts** | 2 | 41 | Authentication: User model, EmailBackend, departments |
| **tickets** | 21 | 122 | Core ticket/incident management: tickets, SLA, notes, attachments, surveys, bulk import |
| **services** | 5 | 1 | Service catalog & service requests |
| **inventory** | 5 | 2 | Stock items, movements, reservations, purchase receipts |
| **monitoring** | 12 | 38 | Monitoring sources, events, alerts, escalation policies, automation policies |
| **procurement** | 21 | 10 | Purchase requests, orders, invoices, vendor returns, financial history |
| **changes** | 22 | 43+ | Change management: change requests, templates, tasks, risk assessments, approvals, blackout periods, outages, dashboard, reports |
| **problem_management** | 19 | 19 | Problem tracking: problems, root cause analysis, actions, evidence, timelines, workarounds |
| **licensing** | 9 | 6 | Software products, license agreements, allocations, compliance findings |
| **cmdb** | 10 | 18 | Configuration items, baselines, drift findings, service profiles, links |
| **lifecycle** | 7 | 2 | Lifecycle templates, cases, tasks, evidence, asset resolutions |
| **workflow** | 3 | 1 | Automation rules, rule executions, approval requests |
| **approval_center** | 0 | 3 | Read-only aggregation of pending approvals across modules (aggregation only, no write logic) |
| **backup** | 3 | 1 | Backup schedules, jobs, restore points |

## Core Essential (FUNCTIONALITY + SECURITY MUST-KEEP)

### 1. Django Core (builtin)
- `django.contrib.admin`, `auth`, `contenttypes`, `sessions`, `messages`, `staticfiles`
- **Reason**: Fundamental Django framework, security, authentication session management

### 2. `accounts` 
- User model, EmailBackend authentication
- **Reason**: Core authentication; security-critical (login, user management)

### 3. `common`
- Soft-delete infrastructure, AuditLog (append-only), Notification system, PrivacyErasureRequest, DataRetentionPolicy, HealthCheckResult, OperationalErrorEvent, OperationalAlert, OperationalIncident
- **Reason**: Foundational infrastructure used by almost all other apps; audit/compliance; security notification framework

### 4. `tickets`
- Core ticket lifecycle, SLA, notes, attachments, surveys, canned responses, templates
- **Reason**: Primary IT service management functionality

### 5. `services`
- Service catalogue items, service requests, requests/comments/history/attachments
- **Reason**: Service request management functionality

## Potential Bloat Candidates (Can Remove With Permission)

These apps provide optional/optional-domain functionality that may be unnecessary for a minimal installation:

### 6. `monitoring` (12 models, 38 URL patterns)
- Monitoring sources, events, alerts, escalation policies
- **Consider removing if**: Not using monitoring dashboards/alerts

### 7. `licensing` (9 models, 6 URL patterns)
- Software products, license agreements, allocations, compliance
- **Consider removing if**: Not license compliance requirements

### 8. `cmdb` (10 models, 18 URL patterns)
- Configuration items, baselines, drift findings
- **Consider removing if**: Not CMDB requirements

### 9. `problem_management` (19 models, 19 URL patterns)
- Problem tracking, root cause analysis, actions, workarounds
- **Consider removing if**: Not problem management process

### 10. `procurement` (21 models, 10 URL patterns)
- Purchase requests, orders, invoices, vendor returns
- **Consider removing if**: Not procurement process

### 11. `lifecycle` (7 models, 2 URL patterns)
- Lifecycle templates, cases, tasks, evidence
- **Consider removing if**: Not lifecycle management

### 12. `changes` (22 models, 43+ router registrations)
- Change requests, templates, tasks, risk assessments, approvals, blackout periods, outages, dashboard, reports
- **Consider removing if**: Not change management ITIL process

### 13. `backup` (3 models, 1 URL pattern)
- Backup schedules, jobs, restore points
- **Consider removing if**: Not backup management

### 14. `workflow` (3 models, 1 URL pattern)
- Automation rules, rule executions, approval requests
- **Consider removing if**: Not workflow automation

### 15. `approval_center` (0 models, 3 URL patterns)
- Read-only aggregation of pending approvals across modules
- **Note**: Depends on other apps (services, assets, workflow, procurement); read-only only

## Recommendation

For a **"churn and delete" operation**, I recommend starting with these steps:

1. **Keep absolutely**: `accounts`, `common`, `tickets`, `services`, `inventory`, Django core
2. **Review for removal**: All other apps (`monitoring`, `licensing`, `cmdb`, `problem_management`, `procurement`, `lifecycle`, `changes`, `backup`, `workflow`, `approval_center`)
3. **Security**: Keep all security middleware, permissions, JWT auth configured in `settings.py`

**Critical warning**: The `approval_center` app is read-only aggregation and depends on other apps' models. Removing source apps will break the approval center.

---

## Next Steps
Please confirm which apps you want me to delete, or give me permission to proceed with removing the bloated apps. I will:
1. Remove the app directories and configuration
2. Update `INSTALLED_APPS` in settings.py
3. Remove URL route references
4. Ensure security configurations remain intact

Do you want me to proceed with removing specific apps? If so, which ones?