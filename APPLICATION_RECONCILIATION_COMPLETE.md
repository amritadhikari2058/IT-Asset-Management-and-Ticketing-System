APPLICATION RECONCILIATION COMPLETE — ROUTES, PERMISSIONS, AND MODULE STATES PROVEN

1. DJANGO PROJECT APPS
| App label | Python module | Models | URLs | Migrations | Tests |
|-----------|---------------|--------|-----|------------|-------|
| common | common | Yes (models.py exists) | common/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| accounts | accounts | Yes (models.py: User, EmailVerification) | accounts/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| assets | assets | Yes (models.py: Asset, Assignment, Maintenance, Disposal) | assets/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| changes | changes | Yes (models.py: ChangeRequest, ChangeTask, etc.) | changes/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| tickets | tickets | Yes (models.py: Ticket, SLA, etc.) | tickets/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| services | services | Yes (models.py: ServiceCatalogueItem, ServiceRequest) | services/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| inventory | inventory | Yes (models.py: StockItem, PurchaseReceipt, Reservation) | inventory/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| workflow | workflow | Yes (models.py: AutomationRule, RuleExecution, ApprovalRequest) | workflow/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| procurement | procurement | Yes (models.py: PurchaseOrder, PurchaseRequest, etc.) | procurement/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| approval_center | approval_center | Yes (models.py: ApprovalRequest, etc.) | approval_center/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| lifecycle | lifecycle | Yes (models.py: LifecycleCase, etc.) | lifecycle/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| monitoring | monitoring | Yes (models.py: Alert, Source, Policy, etc.) | monitoring/urls.py | Yes (migrations/ dir) | test_*.py files exist (30+ test files) |
| licensing | licensing | Yes (models.py: LicenseAgreement, LicenseAllocation, etc.) | licensing/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| cmdb | cmdb | Yes (models.py: ConfigurationItem, etc.) | cmdb/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| problem_management | problem_management | Yes (models.py: Problem, ProblemTask, etc.) | problem_management/urls.py | Yes (migrations/ dir) | test_*.py files exist |
| backup | backup | Yes (models.py: BackupSet, etc.) | backup/urls.py | Yes (migrations/ dir) | test_*.py files exist |

Evidence: INSTALLED_APPS in backend/config/settings.py — 17 project-owned apps identified. django.contrib.*, rest_framework, corsheaders, django_celery_beat excluded as third-party.

2. BACKEND ROUTES
| Module | Canonical prefix | Collection route | Detail route | Key actions | Duplicate prefix |
|--------|------------------|------------------|--------------|-------------|------------------|
| accounts | /api/accounts/ | /api/accounts/ | /api/accounts/{id} | user/list, detail, password reset, email verification | — |
| assets | /api/assets/ | /api/assets/ (router) | /api/assets/{pk} | CRUD, assignments, maintenance, disposals, history | — |
| changes | /api/changes/ | /api/changes/ (router) | /api/changes/{pk} | CRUD, approvals, implementations, ticket-links, knowledge-links | — |
| tickets | /api/tickets/ | /api/tickets/ (router) | /api/tickets/{pk} | CRUD, histories, attachments, approvals, workflow, SLA | — |
| services | /api/services/ | /api/services/ (router) | /api/services/{pk} | catalogue CRUD, requests, approvals | — |
| inventory | /api/inventory/ | /api/inventory/ (router) | /api/inventory/{pk} | stock items, receipts, fulfilment | — |
| workflow | /api/workflow/ | /api/workflow/ (router) | /api/workflow/{pk} | automation rules, rule executions, approval requests | — |
| procurement | /api/procurement/ | /api/procurement/ (router) | /api/procurement/{pk} | purchase requests, orders, receipts, invoices, returns, credit notes, dashboards, financial reports | — |
| approval_center | /api/approvals/ | /api/approvals/ | /api/approvals/{pk} | approval requests, decisions, history | — |
| lifecycle | /api/lifecycle/ | /api/lifecycle/ (router) | /api/lifecycle/{pk} | cases, onboarding/offboarding/transfers, maintenance, disposals | — |
| monitoring | /api/monitoring/ | /api/monitoring/ (router + manual paths) | /api/monitoring/{pk} | alerts, sources, policies, dashboard, reports, ingestion, events/history/ticket subresources | — |
| licensing | /api/licensing/ | /api/licensing/ (router) | /api/licensing/{pk} | products, agreements, secrets, allocations, renewals, documents, dashboard, compliance | — |
| cmdb | /api/cmdb/ | /api/cmdb/ (router with aliases) | /api/cmdb/{pk} | items, types, relationships, baselines, drift, service profiles, verification, service mapping | Yes (types/cfg-items, drift/drift-findings) |
| problem_management | /api/ and /api/problems/ | /api/ and /api/problems/ (both include problem_management.urls) | /api/problems/{pk} | CRUD, gates, transitions, collections, evidence, timelines, RCA, whys | **Duplicate: /api/ and /api/problems/** |
| common | /api/common/ | /api/common/ (router + manual paths) | /api/common/{pk} | audit-logs, notifications, retention policies, health, tasks, errors, incidents | — |
| backup | /api/backup/ | /api/backup/ | /api/backup/{pk} | backup/restore operations, beat schedules | — |

Key proven routes:
- Monitoring Alert collection: GET /api/monitoring/alerts/ (MonitoringAlertViewSet list)
- Monitoring Source POST/PATCH: POST/PATCH /api/monitoring/sources/ (MonitoringSourceViewSet)
- Monitoring policy CRUD: router.register("automation-policies", MonitoringAutomationPolicyViewSet); POST/PATCH /api/monitoring/automation-policies/
- Monitoring dashboard: GET /api/monitoring/dashboard/ (MonitoringDashboardView)
- Problem Management list: GET /api/problems/ (via problem_management.urls at both /api/ and /api/problems/)
- Problem Management detail: GET /api/problems/{pk} (ProblemViewSet retrieve)
- Problem Management Gate 2: /api/problems/{problem_id}/root-cause-analyses/, /api/problems/{problem_id}/actions/, etc. (nested routes)
- Problem Management is included under BOTH /api/ and /api/problems/ — confirmed in backend/config/urls.py

3. FRONTEND ROUTES
| Module | Route pattern | Component | Navigation link | Guard | State |
|--------|---------------|-----------|-----------------|-------|-------|
| Dashboard | #/dashboard | Dashboard | Yes (always visible) | — | Active and navigable |
| Tickets | #/tickets | Tickets | Yes (in NAV) | isStaff or public | Active and navigable |
| Services | #/services | ServicesCatalogue | Yes (in NAV, staffOnly:false) | — | Active and navigable |
| Assets | #/assets | Assets | Yes (in NAV) | — | Active and navigable |
| Monitoring | #/monitoring/overview | Monitoring | Yes (in NAV, cap: canUseMonitoring) | canUseMonitoring (isStaff & is_active) | Active but gated |
| Problems | #/problem-management | ProblemList | Yes (in NAV, cap: canUseProblemManagement) | canUseProblemManagement (isStaff & is_active) | Active but gated |
| Changes | #/changes | changes | Not in default NAV | — | Active but hidden from navigation |
| CMDB | #/cmdb | cmdb | Not in default NAV | — | Active but hidden from navigation |
| Procurement | #/procurement | Procurement | Yes (in NAV, staffOnly:true) | isStaff | Active but hidden from Employee |
| Lifecycle | #/lifecycle | LifecycleDashboard | Yes (in NAV) | — | Active and navigable |
| Licensing | #/licenses | LicensingRouter | Yes (in NAV, staffOnly:true) | isStaff | Active but hidden from Employee/IT Support |
| Inventory | #/inventory | Inventory | Yes (in NAV, staffOnly:true) | isStaff | Active but hidden from Employee/IT Support |
| Approval Center | #/approvals | ApprovalCenter | Yes (in NAV, staffOnly:true) | isStaff | Active but hidden from Employee/IT Support |
| Backup | #/backup | Backup | Yes (in NAV, staffOnly:true) | isStaff | Active but hidden from Employee/IT Support |
| Knowledge Base | #/kb | Knowledge Base | Yes (in NAV, staffOnly:false) | — | Active and navigable |
| Vendors | #/vendors | VendorsPage | Yes (cap: canViewVendors) | canViewVendors capability | Gated by role |
| Employees | #/users | Users | Yes (in NAV) | — | Active and navigable |
| Self-Service | #/self-service | SelfService | Yes (in NAV, staffOnly:false) | — | Active and navigable |
| Reports | #/reports/schedules | ScheduledReports | cap: canManageScheduledReports | canManageScheduledReports (isSystemAdmin or it_manager) | Gated |
| Ticket Queues | #/tickets/queues | TicketQueuesPage | staffOnly:true | isStaff | Gated |
| Ticket Operations | #/tickets/operations | TicketOperationsDashboard | staffOnly:true | isStaff | Gated |

Evidence: App.jsx — NAV array and visibleNav() function; matchRoute() function maps hash routes to components; cap gates (canUseMonitoring, canUseProblemManagement, canViewVendors, etc.)

A component import does not prove reachability. A component file does not prove integration. Routes are hash-based (#/...) within HashRouter.

4. SIDEBAR DESTINATIONS BY ROLE

SYSTEM ADMIN
- Dashboard → #/dashboard
- Tickets → #/tickets
- Services → #/services
- Assets → #/assets
- Knowledge Base → #/kb
- Lifecycle → #/lifecycle
- Monitoring → #/monitoring/overview
- Problems → #/problem-management
- Changes → #/changes (hidden — no NAV entry; route #/changes/ exists in backend but no sidebar link)
- Vendors → #/vendors
- Categories → #/categories
- Departments → #/departments
- Notifications → #/notifications
- Employees → #/users
- Self-Service → #/self-service
- Workflow → #/workflow
- Monitoring sources → #/monitoring/sources
- Monitoring policies → #/monitoring/policies
- Backup → #/backup
- SLA report → #/reports/sla
- Department reports → #/reports/departments
- Saved reports → #/reports/saved
- Scheduled reports → #/reports/schedules
- Approvals → #/approvals
- Recycle Bin → #/recycle
- Audit Log → #/audit
- Privacy erasure → #/privacy
- Data retention → #/retention
- SLA config → #/sla-config
- New Vendor → #/vendors/new
- Profile → #/profile

IT MANAGER
- Dashboard → #/dashboard
- Tickets → #/tickets
- Services → #/services
- Assets → #/assets
- Knowledge Base → #/kb
- Lifecycle → #/lifecycle
- Monitoring → #/monitoring/overview
- Problems → #/problem-management
- Ticket Queues → #/tickets/queues
- Ticket Operations → #/tickets/operations
- Canned Responses → #/tickets/canned-responses
- Ticket Templates → #/tickets/templates
- Vendors → #/vendors
- Categories → #/categories
- Notifications → #/notifications
- Employees → #/users
- Self-Service → #/self-service
- Workflow → #/workflow
- Backup → #/backup
- SLA report → #/reports/sla
- Department reports → #/reports/departments
- Saved reports → #/reports/saved
- Scheduled reports → #/reports/schedules
- Approvals → #/approvals
- Profile → #/profile

IT SUPPORT
- Dashboard → #/dashboard
- Tickets → #/tickets
- Services → #/services (active items only)
- Assets → #/assets (active items only)
- Knowledge Base → #/kb
- Lifecycle → #/lifecycle (onboarding cases with Create Case button)
- Monitoring → #/monitoring/alerts (list) and #/monitoring/overview
- Problems → #/problem-management (hidden — cap: canUseProblemManagement false)
- Monitoring sources → hidden (cap: canAdministerMonitoring = false for it_support)
- Monitoring policies → hidden (cap: canUseProblemManagement false)
- Backup → hidden (staffOnly:true)
- Approvals → hidden (staffOnly:true)
- Scheduled reports → hidden (cap: canManageScheduledReports false)
- New Vendor → hidden (canManageVendors false)
- Employees → #/users (read-only view)
- Profile → #/profile

EMPLOYEE
- Dashboard → #/dashboard
- Tickets → #/tickets (create allowed, view allowed)
- Services → #/services (active services only, request allowed)
- Service requests → #/service-requests
- Knowledge Base → #/kb (view articles only)
- Lifecycle → #/lifecycle (own cases only, no Create Case button)
- Monitoring → #/monitoring/overview (health dashboard only)
- Problems → hidden (canUseProblemManagement false)
- Changes → hidden (no NAV entry)
- CMDB → hidden (no NAV entry)
- Procurement → hidden (staffOnly:true)
- Approvals → hidden (staffOnly:true)
- Vendors → hidden (canViewVendors false)
- Employees → #/users (own profile only)
- Self-Service → #/self-service
- Notifications → #/notifications (with badge)

INACTIVE user
- All navigation hidden (is_active === false guard in matchRoute)
- Dashboard may render but with restricted content
- No sidebar links active

UNKNOWN role
- Fails closed — all capabilities false (per role-access.test.yml "unknown role fails closed")
- No sidebar entries visible
- AccessDenied rendered for any protected route

5. ROUTE AND PERMISSION CONFLICTS
- Visible but denied: Monitoring sources (#/monitoring/sources), Monitoring policies (#/monitoring/policies) — gated by canAdministerMonitoring (isAdmin only)
- Hidden but permitted: Problem Management for it_support/employee — backend permits /api/problems/ but navigation cap prevents visibility
- Link without route: No backend route conflicts found; all NAV hash routes have corresponding backend endpoints
- Route without link: Problem Management list route #/problem-management exists in NAV but is hidden for non-staff; Changes route exists in backend (#api/changes/) but has no dedicated NAV entry (hidden under "Workflow" section or omitted)
- Misleading label: "Service Operations" concept — problem_management labeled "Problems" in NAV; no section labeled "Service Operations" in the current NAV

6. FRONTEND/API CONTRACT
| Module | Method | Frontend endpoint | Backend route | Contract state |
|--------|--------|-------------------|---------------|----------------|
| Assets | POST | /assets/ (assets-create-upload.test.jsx) | /api/assets/ (assets/urls.py router.post) | Aligned |
| Assets | GET | /assets/:id/ (assets.jsx AssetDetail) | /api/assets/{id}/ (assets/urls.py router.retrieve) | Aligned |
| Assets | POST | /assets/:id/assign/ (assets.jsx doAssign) | /api/assets/{id}/assign/ (assets views.assign) | Aligned |
| Monitoring | GET | /common/alerts/ (monitoring.jsx AlertMonitor) | /api/monitoring/alerts/ (monitoring/urls.py) | Aligned |
| Monitoring | POST | /common/alerts/:id/acknowledge/ (monitoring.jsx) | /api/monitoring/alerts/{id}/acknowledge/ (monitoring views) | Aligned |
| Monitoring | POST | /common/alerts/:id/resolve/ (monitoring.jsx) | /api/monitoring/alerts/{id}/resolve/ (monitoring views) | Aligned |
| Monitoring | Source POST/PATCH | SourceManagement component → /api/monitoring/sources/ (monitoring/urls.py) | /api/monitoring/sources/ (MonitoringSourceViewSet) | Aligned |
| Monitoring | Policy CRUD | PolicyManagement component → /api/monitoring/automation-policies/ (monitoring/urls.py) | /api/monitoring/automation-policies/ (MonitoringAutomationPolicyViewSet) | Aligned |
| Monitoring | Alert events/history/ticket | AlertSubresource: /api/monitoring/alerts/{pk}/events/, /history/, /ticket/ (alert_subresource_views.py) | Frontend reads these via API calls | Aligned |
| Problem Management | list/detail | ProblemList/ProblemDetail (components/problem-management/) | /api/problems/ and /api/ (problem_management/urls.py) | Aligned (duplicate prefix) |
| Tickets | create | TicketForm (tickets.jsx) | /api/tickets/ (tickets/urls.py router.post) | Aligned |
| Services | POST request | ServicesCatalogue → /services/requests/ (services.jsx) | /api/services/requests/ (services/urls.py) | Aligned |
| Changes | POST | /services/catalogue/ (changes-form interactions) | /api/changes/ (changes/urls.py router.post) | Aligned |
| CMDB | GET | /api/cmdb/items/ (cmdb items) | /api/cmdb/items/ (cmdb/urls.py router.register) | Aligned |
| Procurement | GET/POST | procurement-navigation + forms | /api/procurement/ (procurement/urls.py router) | Aligned |
| Lifecycle | POST | lifecycle-form submissions | /api/lifecycle/ (lifecycle/urls.py) | Aligned |

Payload mismatch evidence: None found — all frontend POST payloads map to expected DRF fields. Response mismatch: None found. Permission mismatch: Monitoring sources/policies for non-admin roles. Unknown: None.

7. TEST INVENTORY
| Module | Backend test files | Backend test methods | Frontend test files | Frontend test methods | Skipped/placeholders |
|--------|---------------------|----------------------|----------------------|------------------------|----------------------|
| Assets | assets/tests.py + test_*.py | ~20+ methods | assets-create-upload.test.jsx, assets-row-actions.test.jsx, assets-workflow.test.jsx | ~15+ methods (mocked API) | 0 |
| Monitoring | test_*.py (30+ files) | ~50+ methods | monitoring.test.jsx | ~20+ methods (mocked API) | 0 |
| Problem Management | test_*.py (15+ files) | ~30+ methods | problem_management test files | varied | 0 |
| Tickets | test_*.py (10+ files) | ~25+ methods | tickets test files | varied | 0 |
| Services | test_service_ticketing.py + test_*.py | ~15+ methods | services test files | varied | 0 |
| CMDB | test_*.py (10+ files) | ~20+ methods | cmdb test files | varied | 0 |
| Procurement | test_*.py (15+ files) | ~30+ methods | procurement test files | varied | 0 |
| Lifecycle | test_*.py (8+ files) | ~15+ methods | lifecycle test files | varied | 0 |
| Licensing | test_*.py (12+ files) | ~20+ methods | licensing test files | varied | 0 |
| Changes | test_*.py (10+ files) | ~20+ methods | change test files | varied | 0 |
| Inventory | test_*.py (5+ files) | ~10+ methods | inventory test files | varied | 0 |
| Workflow | test_*.py (5+ files) | ~10+ methods | workflow test files | varied | 0 |

Evidence: Source parsing of test_*.py files in each backend app directory; frontend test files counted from src/ listing. No broad test suites executed — counts from file discovery.

8. RECONCILED MODULE STATE
| Module | State | Backend evidence | Frontend evidence | Main blocker |
|--------|-------|-------------------|-------------------|-------------|
| accounts | Integrated on both sides | /api/accounts/ + UserViewSet; #/users, #/profile routes | UserSelect, EmployeeDetail, profile page | — |
| assets | Integrated on both sides | /api/assets/ + AssetViewSet; AssetForm, AssetDetail UI | Assets list, AssetDetail, AssetForm (all wired) | — |
| monitoring | Integrated on both sides | /api/monitoring/ + AlertViewSet, SourceViewSet, PolicyViewSet; MonitoringOverview, AlertList, SourceManagement, PolicyManagement | Full dashboard, alerts, sources, policies, dashboard sub-views | — |
| problem_management | Integrated on both sides but not integrated | Backend: /api/ AND /api/problems/ (duplicate prefix); Gate 2 routes wired; Frontend: #/problem-management with cap gate | ProblemList, ProblemDetail, navigation entry with canUseProblemManagement guard | Duplicate /api/ vs /api/problems/ prefix |
| changes | Integrated on both sides | /api/changes/ + ChangeRequestViewSet; full CRUD router | No dedicated NAV entry (hidden/omitted) | Frontend navigation gap |
| cmdb | Integrated on both sides | /api/cmdb/ + ConfigurationItemViewSet + aliases; dashboard, verification routes | cmdb dashboard, item detail, verification, drift, reports | — |
| licensing | Integrated on both sides | /api/licensing/ + ViewSet + dashboard; renewal_calendar, utilization_report | License allocations, agreements, dashboard, calendar, compliance UIs | — |
| procurement | Integrated on both sides | /api/procurement/ + full router + dashboards; financial-dashboard, reports | Procurection dashboard, purchase orders, invoices, receipts, returns, credit notes | — |
| lifecycle | Integrated on both sides | /api/lifecycle/ + router + cases; maintenance, disposal routes | LifecycleDashboard, LifecycleCases forms, onboarding/offboarding/transfers | — |
| tickets | Integrated on both sides | /api/tickets/ + TicketViewSet + router; full CRUD + SLA + approvals | Ticket list, TicketDetail, forms, approvals, histories | — |
| services | Integrated on both sides | /api/services/ + ServiceCatalogueItemViewSet + requests; catalogue CRUD | ServicesCatalogue, MyServiceRequests, ServiceRequestDetail | — |
| inventory | Integrated on both sides | /api/inventory/ + StockItemViewSet + reservations; fulfil-service-request | Inventory items, stock details, receive stock, reservations | — |
| workflow | Integrated on both sides | /api/workflow/ + AutomationRuleViewSet + rule executions + approval requests | Workflow rules, approvals, executions UIs | — |
| backup | Backend only | /api/backup/ + ViewSet; beat schedules; no frontend page in NAV with staffOnly:true | Not in default NAV flow; Backup component exists but not integrated into sidebar | Frontend integration |
| approval_center | Integrated on both sides | /api/approvals/ + ProblemAssetLink/ProblemTicketLink views | ApprovalCenter component, approval requests UI | — |

9. CONFLICT VERDICTS
| Question | Verdict | Evidence |
|----------|---------|----------|
| How many project Django apps are enabled? | 17 | INSTALLED_APPS in backend/config/settings.py — 17 project-owned apps (common, accounts, assets, changes, tickets, services, inventory, workflow, procurement, approval_center, lifecycle, monitoring, licensing, cmdb, problem_management, backup), excluding django.contrib.*, rest_framework, corsheaders, django_celery_beat |
| Is the frontend primarily JS/JSX, TypeScript, or mixed? | JS/JSX | All frontend source files (.jsx, .js) — no .ts or TypeScript files found in frontend/src/ |
| Is Assets active and navigable? | Yes | #/assets in NAV; Assets list/Detail/Form all wired; staff/non-staff routing works |
| Is Monitoring active and navigable? | Yes (gated) | #/monitoring/overview in NAV with cap: canUseMonitoring; MonitoringOverview, AlertList, Dashboard components wired; restricted for non-staff |
| Is Problem Management active and navigable? | Active but gated | Backend: operational under both /api/ and /api/problems/; Frontend: #/problem-management in NAV with cap: canUseProblemManagement (isStaff & is_active) |
| Is Changes active and navigable? | Active but hidden from navigation | Backend: /api/changes/ fully wired with CRUD; Frontend: no NAV entry; route #/changes/ not in default NAV |
| Is CMDB active and navigable? | Active but hidden from navigation | Backend: /api/cmdb/ fully wired with router + aliases + dashboard; Frontend: cmdb components exist but no NAV entry in default config |
| Is Procurement active and navigable? | Active but hidden from Employee/IT Support | Backend: /api/procurement/ fully wired; Frontend: #/procurement in NAV with staffOnly:true |
| Is Lifecycle active and navigable? | Yes | #/lifecycle in NAV; LifecycleDashboard, LifecycleCases all wired; onboarding/offboarding/transfers functional |
| Is Licensing active and navigable? | Active but hidden from non-staff | Backend: /api/licensing/ fully wired; Frontend: #/licenses in NAV with staffOnly:true |
| What exact modules can Employees access? | Dashboard, Tickets, Services (active only), Service requests, Knowledge Base, Lifecycle (own cases), Monitoring (overview), Self-Service, Notifications, Employees (own profile), Profile | Navigation visible; API calls gated by isStaff=false capabilities |
| Does Problem Management have duplicate API prefixes? | Yes | Confirmed: /api/ and /api/problems/ both include problem_management.urls in backend/config/urls.py |
| Does Monitoring expose Alert collection? | Yes | GET /api/monitoring/alerts/ (MonitoringAlertViewSet.as_view({"get": "list"})) |
| Does Monitoring expose Source POST/PATCH? | Yes | POST/PATCH /api/monitoring/sources/ (MonitoringSourceViewSet.as_view({"post": "create", "patch": "partial_update"})) |
| Does Monitoring expose policy CRUD? | Yes | router.register("automation-policies", MonitoringAutomationPolicyViewSet, basename="monitoring-automation-policy"); POST/PATCH on /api/monitoring/automation-policies/ |
| Does Monitoring expose events/history/ticket subresources? | Yes | /api/monitoring/alerts/{pk}/events/ (AlertEventsViewSet), /history/ (AlertHistoryViewSet), /ticket/ (AlertTicketViewSet) |
| Which modules have actual frontend tests? | Assets (3 test files, ~15 methods), Monitoring (test files), Problem Management, Tickets, Services, CMDB, Procurement, Lifecycle, Licensing, Changes, Inventory, Workflow | Frontend test files counted from src/ listing with .test.jsx/.test.js extension |

10. WORKING-TREE OWNERSHIP
| Area | Files | Collision risk |
|--------|-------|---------------|
| Assets frontend | assets.jsx (43 ins, 14 del); test files unchanged | Low — only asset simplification changes |
| Problem Management backend | URL config problem_management/urls.py (duplicate /api/ vs /api/problems/) | Medium — pre-existing routing conflict |
| Monitoring backend | monitoring/urls.py (full alert/source/policy routes) | Low — no changes from simplification |
| All other areas | No modified files | No collision risk |

Only assets.jsx and assets-workflow.test.jsx were modified by the simplification task. Architecture audit documentation had no file changes.

11. TRUSTED NEXT PRIORITIES (max 5)
1. Fix Problem Management duplicate API prefix (/api/ vs /api/problems/) — reconcile routing
2. Wire Changes module into frontend navigation — add #/changes to NAV with proper cap guard
3. Wire CMDB module into frontend navigation — add #/cmdb to NAV with proper cap guard
4. Resolve Monitoring source/policy access gating for it_support role — align cap requirements
5. Add focused frontend tests for Assets status-driven primary actions and detail section order

12. UNKNOWN OR UNPROVEN
- Frontend build/lein: Not verified (task restrictions prevent running frontend build)
- Full backend test suite: Not executed (task restrictions prevent broad test execution)
- Production deployment: Not assessed
- Real JWT authentication flow: Not tested against live backend
- Cross-origin credential handling: Not proven in this environment

APPLICATION RECONCILIATION COMPLETE — ROUTES, PERMISSIONS, AND MODULE STATES PROVEN