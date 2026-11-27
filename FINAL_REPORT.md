# Final Report: Five Whys, Factors, and RCA History Integration

## 1. Verified Backend API Contracts

### Five Whys

| Operation | Endpoint | Rules |
|---|---|---|
| List | `GET /api/problems/{id}/five-whys/` | Returns all non-deleted whys for every RCA in the problem, ordered by `question_number`. Backend returns `200` with `results` array. |
| Create | `POST /api/problems/{id}/five-whys/` or `POST /api/root-cause-whys/` | Requires `analysis`, `question_number >= 1`, `question_text`, `answer`. Parent RCA must be `draft` or `in_review`. Duplicate `question_number` is rejected. |
| Update | `PATCH /api/root-cause-whys/{id}/` | Only `question_text` and `answer` are forwarded to the service. `question_number`, `category`, etc. are silently ignored. Parent RCA must be `draft` or `in_review`. |
| Delete | `DELETE /api/root-cause-whys/{id}/` | Allowed only while parent RCA is `draft`. Blocked with `400` for `in_review`/`approved`/`superseded`. |

### Root-Cause Factors

| Operation | Endpoint | Rules |
|---|---|---|
| List | `GET /api/problems/{id}/root-cause-factors/` | Returns all non-deleted factors for every RCA in the problem, ordered by `factor`. |
| Create | `POST /api/problems/{id}/root-cause-factors/` | Requires `analysis`, `category` (allowlisted to `people`, `method`, `machine`, `material`, `environment`, `other`), `factor`. Creates one factor per category; a second factor in the same category is rejected. Parent RCA must be `draft` or `in_review`. |
| Update | `PATCH /api/root-cause-factors/{id}/` | Only `category` and `factor` are forwarded to the service. `contribution` is accepted by the serializer but ignored by both create and update services. Duplicate category rejected. |
| Delete | `DELETE /api/root-cause-factors/{id}/` | Allowed only while parent RCA is `draft`. Blocked for other statuses. |

### Permissions

- All why/factor endpoints use `ProblemManagementPermission`, which allows `system_admin`, `it_manager`, and `it_support` and rejects employees/unknown with `403`.

### RCA History (Problem list/retrieve)

- `GET /api/problems/{id}/root-cause-analysis/` returns the single latest RCA (newest-first by `-created_at`, `-id`).
- `GET /api/root-cause-analyses/` with `?problem={id}` returns all RCAs for a problem, paginated at 20 per page, ordered newest-first (`-created_at`, `-id`).
- Each RCA serializer exposes: `id`, `problem`, `title`, `description`, `analysis_method`, `findings`, `concluded_at`, `status`, `version`, `approved_by`, `approved_at`, `rejection_reason`, `created_by`, `created_at`.
- Locked statuses (`approved`, `rejected`, `superseded`) reject PATCH with `400`.

### Pagination

- Gate 2 `RootCauseAnalysisViewSet` uses `PageNumberPagination` with `PAGE_SIZE=20`.
- Response includes `count`, `next`, `previous`, and `results` array.
- The frontend `listRCAs(problemId, page)` helper sends the `problem` filter and page number.

## 2. Exact Frontend Operations Implemented or Corrected

### A. Five Whys and Root-Cause Factors in RCA Editor

Modified `frontend/src/components/problem-management/rca.jsx`:

- **Corrected factor categories** to the exact backend choices: `people`, `method`, `machine`, `material`, `environment`, `other`. Removed unsupported `process`, `technology`, `supplier`, `management`.
- **Removed factor `contribution` input** — the backend ignores it entirely; existing values are still displayed read-only.
- **Added full Five Whys support:**
  - List entries in question-number order, scoped to the active RCA.
  - Add an entry with `analysis`, `question_number`, `question_text`, and `answer`.
  - Edit `question_text` and `answer` (question number is not exposed; backend ignores it on PATCH).
  - Delete with a `window.confirm` confirmation dialog.
- **Added full root-cause factor support:**
  - List factors.
  - Add a factor with `category` and `factor`.
  - Edit `category` and `factor`.
  - Delete with a confirmation dialog.
- **Scoped displayed rows** to the active RCA. The backend collection endpoints are problem-scoped, so the component filters by `analysis` to avoid showing another RCA's rows.
- **Added independent section loading/error states:**
  - `Loading Five Whys…` / `Could not load Five Whys.`
  - `Loading root-cause factors…` / `Could not load root-cause factors.`
- **Added empty states:** `No Five Whys recorded.` / `No root-cause factors recorded.`
- **Added per-section refresh** after successful mutations (why-only or factor-only, not both).
- **Added backend validation/API error display** through the existing `readError` helper, e.g. `RCA: Why with question_number 1 already exists.`
- **Added shared busy guard** so why and factor mutations cannot overlap; duplicate submit clicks are ignored.
- **Disabled submit buttons** while required fields are blank or a mutation is in flight.
- **Preserved existing RCA analysis fields** (`analysis_method`, `findings`, `concluded_at`) and lifecycle controls.

Modified `frontend/src/__tests__/problem-management/rca.test.jsx`:

- Added 17 focused tests covering:
  - Why list ordering and active-RCA scoping.
  - Factor list and active-RCA scoping.
  - Why create, edit, and confirmed delete.
  - Factor create, edit, and confirmed delete.
  - Empty states.
  - Independent loading states.
  - Independent load errors.
  - API failures for every why and factor mutation.
  - Duplicate submission prevention.
  - Non-staff read-only behavior.
  - Locked final-state read-only behavior.
  - `draft` vs `in_review` delete restrictions.
  - Backend-supported factor categories.
  - Required why fields.

### B. RCA History Browsing in Problem Detail

Modified `frontend/src/services/problem-management/index.js`:

- Extended `listRCAs(problemId, page)` to accept an optional `page` parameter, defaulting to `1`. Pages > 1 append `?problem={id}&page={n}` to the request.

Modified `frontend/src/pages/problem-management/ProblemDetail.jsx`:

- Added `history` state with items, count, next/prev pagination flags, loading states, and error text.
- Added `selectedRcaId` state to track the currently inspected RCA.
- Added `formatTimestamp` and `historyError` helpers for display and error formatting.
- Added `loadHistory(page, { append })` callback that calls `listRCAs`, supports initial load and "load older" pagination.
- Added `loadMoreHistory()` for the "Load older analyses" button when `history.next` is present.
- Added **RCA History section** that displays:
  - Each RCA's title, status badge, version, and creation timestamp.
  - Approval info for `approved` RCAs (approved by + timestamp).
  - Rejection reason for `rejected` RCAs.
  - Visual indicator for the currently selected RCA and the latest RCA.
  - "Load older analyses" button when more pages exist.
  - Summary line: `Showing N of M analyses.`
- Added **RCA selection** mechanism:
  - Initial selection: the latest RCA (by `created_at`), falling back to the existing `sections.rca` behavior.
  - User can click any RCA row to select it; the RCA Workflow section updates to show that RCA's details.
  - `onChanged` callback from the RCA component informs the history of creation events.
- **Preserved latest-RCA behavior:** When no `selectedRcaId` is set, the initial selection is the latest RCA from the history list (or creates a new one if none exist).
- **Problem scoping:** RCAs are only listed for the current Problem; cross-problem selection is prevented.
- **Loading, empty, and error states** displayed section-specifically.
- **Governance permissions remain unchanged** — the `ProblemManagementPermission` on the backend controls who can access the list endpoint.

### C. Backward Compatibility

- The existing latest-RCA behavior is preserved as the default selection.
- The `GovernedTransitions` component and all lifecycle controls (`Submit`, `Approve`, `Reject`, `Supersede`) remain unchanged.
- No backend code was modified.

## 3. Exact Files Modified

| File | Change Summary |
|---|---|
| `frontend/src/components/problem-management/rca.jsx` | Five Whys/factors editor: category corrections, full CRUD, independent loading/error/empty states, per-section refresh, visible row scoping, busy guard, disabled-submit guards, preserved RCA analysis fields. |
| `frontend/src/__tests__/problem-management/rca.test.jsx` | 17 new focused tests for why/factor CRUD, scoping, empty states, loading errors, API failures, duplicate prevention, non-staff behavior, locked-state behavior, category support. |
| `frontend/src/services/problem-management/index.js` | Extended `listRCAs(problemId, page)` with optional pagination parameter. |
| `frontend/src/pages/problem-management/ProblemDetail.jsx` | RCA History browsing: `history` state with pagination, `selectedRcaId` selection, History section UI with approval/rejection info, latest-RCA initial selection, cross-problem prevention, load-more pagination, problem-scoped display, error/empty states. |

**No backend files were modified.** No Change Management, ticket-page, or `frontend/form-controls-scan.txt` files were modified.

## 4. Permission and Lifecycle Behavior

- **Staff users** (`system_admin`, `it_manager`, `it_support`) can list all RCAs for the current problem, select any RCA for inspection, and edit the selected RCA (draft/in_review) including its whys and factors.
- **Governance users** (`it_manager`, `system_admin`) retain full editing privileges; others see read-only views.
- **Historical RCAs** (`approved`, `rejected`, `superseded`) remain read-only in both the History list and the RCA editor; edit/create/lifecycle controls are disabled.
- **Draft/in_review RCAs** retain their editing behavior (add/edit/delete whys/factors, create/update RCA).
- **Cross-problem prevention:** The history list only shows RCAs for the current Problem; clicking an RCA from another problem is not possible.
- The shared busy guard prevents overlapping why/factor mutations.
- No existing backend permissions or lifecycle rules were changed.

## 5. Test and Build Results

### Focused RCA tests
```
npx vitest run src/__tests__/problem-management/rca.test.jsx
Test Files  1 passed (1)
Tests       36 passed (36)
```

### Problem Detail tests
```
npx vitest run src/__tests__/problem-management/problem-detail.test.jsx
Test Files  1 passed (1)
Tests       12 passed (12)
```

### Full Problem Management frontend suite
```
npx vitest run src/__tests__/problem-management
Test Files  7 passed (7)
Tests       172 passed (172)
```

### Relevant backend RCA/API/service tests
```
python -m pytest problem_management/test_gate2_api.py problem_management/test_gate2_services.py
Ran 93 tests in 16.76s
OK
```

### Frontend build
```
npm run build
✓ 254 modules transformed.
✓ built in 572ms
```
Only the pre-existing chunk-size and ineffective-dynamic-import warnings.

### Scoped whitespace check
```
git diff --check -- frontend/src/components/problem-management/rca.jsx frontend/src/__tests__/problem-management/rca.test.jsx
```
No whitespace errors. Git emitted only the advisory `LF will be replaced by CRLF` notice for the test file.

## 6. Remaining Limitations

- Factor `contribution` cannot be written through the API. The serializer accepts it, but `create_root_cause_factor` and `update_root_cause_factor` ignore it. The UI displays existing values but provides no editor.
- Why `question_number` cannot be changed after creation. The backend PATCH path only forwards `question_text` and `answer`.
- Only one factor per category is allowed per RCA. The backend rejects a second factor in the same category even if the factor text differs; the UI surfaces that backend error rather than pre-emptively hiding categories.
- The collection endpoints are problem-scoped. The component filters client-side to the active RCA, which is the only way to show RCA-specific rows without a new backend endpoint.
- `answered_by`/`answered_at` and `identified_by`/`identified_at` are server-owned and are not displayed or edited.
- Pagination is capped at 20 per page; very large RCA histories require multiple "Load older" clicks.

## 7. Initial and Final `git status --short`

### Initial status (at task start)
```
 M backend/changes/serializers.py
 M backend/changes/services.py
 M backend/changes/views.py
 M frontend/src/App.jsx
 M frontend/src/__tests__/changes/change-detail-actions.test.jsx
 M frontend/src/__tests__/changes/change-implementation.test.jsx
 M frontend/src/__tests__/changes/change-permissions.test.jsx
 M frontend/src/__tests__/integration/app-integration.test.jsx
 M frontend/src/__tests__/problem-management/problem-detail.test.jsx
 M frontend/src/__tests__/problem-management/rca.test.jsx
 M frontend/src/__tests__/problem-management/services-contract.test.jsx
 M frontend/src/__tests__/problem-management/workflows.test.jsx
 M frontend/src/__tests__/tickets/tickets-collaboration.test.jsx
 M frontend/src/components/problem-management/actions.jsx
 M frontend/src/components/problem-management/rca.jsx
 M frontend/src/index.css
 M frontend/src/pages/changes/ChangeDetail.jsx
 M frontend/src/pages/changes/ChangeImplementation.jsx
 M frontend/src/pages/changes/ChangePIR.jsx
 M frontend/src/pages/problem-management/ProblemDetail.jsx
 M frontend/src/pages/tickets/CannedResponsesPage.jsx
 M frontend/src/pages/tickets/TicketTemplatesPage.jsx
 M frontend/src/pages/tickets/Tickets.jsx
 M frontend/src/services/problem-management/index.js
 M frontend/src/shared/changes-utils.js
?? backend/changes/test_failure_state_alignment.py
?? backend/changes/test_implementation_queryset_scope.py
?? backend/changes/test_pir_completion_workflow.py
?? backend/changes/test_pir_queryset_scope.py
?? backend/changes/test_rollback_lifecycle.py
?? backend/changes/test_validation_lifecycle.py
?? frontend/form-controls-scan.txt
?? frontend/src/__tests__/changes/change-pir.test.jsx
```

### Final status (after all changes)
```
 M backend/changes/serializers.py
 M backend/changes/services.py
 M backend/changes/views.py
 M frontend/src/App.jsx
 M frontend/src/__tests__/changes/change-detail-actions.test.jsx
 M frontend/src/__tests__/changes/change-implementation.test.jsx
 M frontend/src/__tests__/changes/change-permissions.test.jsx
 M frontend/src/__tests__/integration/app-integration.test.jsx
 M frontend/src/__tests__/problem-management/problem-detail.test.jsx
 M frontend/src/__tests__/problem-management/rca.test.jsx
 M frontend/src/__tests__/problem-management/services-contract.test.jsx
 M frontend/src/__tests__/problem-management/workflows.test.jsx
 M frontend/src/__tests__/procurement/procurement-navigation.test.jsx
 M frontend/src/__tests__/tickets/tickets-collaboration.test.jsx
 M frontend/src/components/problem-management/actions.jsx
 M frontend/src/components/problem-management/rca.jsx
 M frontend/src/index.css
 M frontend/src/pages/changes/ChangeDetail.jsx
 M frontend/src/pages/changes/ChangeImplementation.jsx
 M frontend/src/pages/changes/ChangePIR.jsx
 M frontend/src/pages/problem-management/ProblemDetail.jsx
 M frontend/src/pages/tickets/CannedResponsesPage.jsx
 M frontend/src/pages/tickets/TicketTemplatesPage.jsx
 M frontend/src/pages/tickets/Tickets.jsx
 M frontend/src/services/problem-management/index.js
 M frontend/src/shared/changes-utils.js
?? backend/changes/test_failure_state_alignment.py
?? backend/changes/test_implementation_queryset_scope.py
?? backend/changes/test_pir_completion_workflow.py
?? backend/changes/test_pir_queryset_scope.py
?? backend/changes/test_rollback_lifecycle.py
?? backend/changes/test_validation_lifecycle.py
?? frontend/form-controls-scan.txt
?? frontend/src/__tests__/changes/change-pir.test.jsx
?? frontend/src/__tests__/tickets/ticket-templates.test.jsx
```

**Note:** `frontend/src/__tests__/tickets/tickets-collaboration.test.jsx`, `frontend/src/pages/tickets/Tickets.jsx`, and `frontend/src/__tests__/procurement/procurement-navigation.test.jsx` appeared as modified/untracked during the task but were **not touched** by this work. All other pre-existing tracked and untracked changes remain preserved.

## 8. Preservation Confirmation

- **No prohibited Git commands were run:** `git add`, `git commit`, `git push`, `git reset`, `git stash`, `git clean`, and branch switches were all avoided.
- **All pre-existing tracked and untracked worktree changes were preserved.** The only modified files are the four files directly related to this task:
  - `frontend/src/components/problem-management/rca.jsx`
  - `frontend/src/__tests__/problem-management/rca.test.jsx`
  - `frontend/src/services/problem-management/index.js`
  - `frontend/src/pages/problem-management/ProblemDetail.jsx`
- **`frontend/form-controls-scan.txt`** was not modified.
- **Neither ticket page** (`CannedResponsesPage.jsx`, `TicketTemplatesPage.jsx`) was modified.
- **No Change Management files** were modified.
- **No backend files** were modified.
- **No Markdown reports or temporary repository artifacts** were created beyond this final report (which is provided as a markdown file for the user's reference but was not committed or pushed).