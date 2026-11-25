import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Badge, ConfirmDialog, DataTable, ErrorSummary, Field,
  PageHeader, Pager, UserSelect,
} from '../../components';
import { parseApiError, fetchPage } from '../../api-utils';
import {
  CASE_TYPE_LABELS, CASE_STATUS_LABELS, PRIORITY_LABELS,
  formatDate, formatDateTime, isTerminalCaseStatus,
} from '../../shared/lifecycle-utils';

const STATUS_OPTIONS = [
  'draft', 'planned', 'in_progress', 'ready_for_employee',
  'employee_started', 'blocked', 'completed', 'cancelled',
];
const PRIORITY_OPTIONS = ['low', 'medium', 'high', 'urgent'];
const SOURCE_OPTIONS = ['manual', 'service_request', 'employee_created', 'department_transfer', 'account_deactivation'];

export function LifecycleCases({ caseType }) {
  const { isStaff, isAdmin, isManagerOrAdmin, isEmployee } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filters, setFilters] = useState({
    status: '', priority: '', employee: '', department: '', coordinator: '',
    planned_from: '', planned_to: '', effective_from: '', effective_to: '',
    target_from: '', target_to: '', blocked: '', overdue: '', source: '', search: '',
  });
  const [confirmCancelId, setConfirmCancelId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState({});

  const canManage = isAdmin || isManagerOrAdmin;
  const canStaff = isStaff;
  const isEmpView = isEmployee && !isStaff;

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const params = {
        page, page_size: pageSize,
        case_type: caseType,
        ...filters,
      };
      const clean = {};
      for (const [k, v] of Object.entries(params)) {
        if (v !== '' && v != null) clean[k] = v;
      }
      const r = await fetchPage('/lifecycle/cases/', { params: clean });
      setItems(r.items);
      setCount(r.count);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load cases.');
    } finally {
      setLoading(false);
    }
  };

  // Reload on mount and whenever filters or pagination change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [caseType, page, pageSize, JSON.stringify(filters)]);

  const doRetry = () => load();

  const hasPrev = page > 1;
  const hasNext = (page * pageSize) < count;

  const doTransition = async (id, action) => {
    setActionBusy((s) => ({ ...s, [id]: true }));
    try {
      const c = items.find((i) => i.id === id);
      const payload = { version: c ? c.version : 1 };
      if (action === 'cancel') payload.reason = 'Cancelled from case list.';
      await api.post(`/lifecycle/cases/${id}/${action}/`, payload);
      load();
    } catch (e) {
      const p = parseApiError(e);
      setError(p.global || `Could not ${action} case.`);
    } finally {
      setActionBusy((s) => { const n = { ...s }; delete n[id]; return n; });
    }
  };

  const doCancel = async () => {
    if (!confirmCancelId) return;
    setDeleteBusy(true);
    try {
      const c = items.find((i) => i.id === confirmCancelId);
      await api.post(`/lifecycle/cases/${confirmCancelId}/cancel/`, {
        reason: 'Cancelled from case list.',
        version: c ? c.version : 1,
      });
      setConfirmCancelId(null);
      load();
    } catch (e) {
      const p = parseApiError(e);
      setError(p.global || 'Could not cancel case.');
    } finally {
      setDeleteBusy(false);
    }
  };

  const rowActions = (c) => {
    const isTerminal = isTerminalCaseStatus(c.status);
    const isDraft = c.status === 'draft';
    const isPlanned = c.status === 'planned';
    const isInProgress = c.status === 'in_progress';
    const busy = !!actionBusy[c.id];
    const buttons = [];

    buttons.push(
      <button key="view" type="button" className="btn-small btn-ghost"
        onClick={() => { location.hash = `#/lifecycle/${c.id}`; }}
        disabled={busy}>
        View
      </button>
    );

    if (isDraft && canManage && !busy) {
      buttons.push(
        <button key="plan" type="button" className="btn-small btn-secondary"
          onClick={() => doTransition(c.id, 'plan')}>
          Plan
        </button>
      );
    }
    if (isPlanned && canStaff && !busy) {
      buttons.push(
        <button key="start" type="button" className="btn-small btn-secondary"
          onClick={() => doTransition(c.id, 'start')}>
          Start
        </button>
      );
    }
    if (isInProgress && canStaff && !busy) {
      buttons.push(
        <button key="resume" type="button" className="btn-small btn-secondary"
          onClick={() => doTransition(c.id, 'unblock')}>
          Resume
        </button>
      );
    }
    if (!isTerminal && canManage && !busy) {
      buttons.push(
        <button key="complete" type="button" className="btn-small btn-outline"
          onClick={() => doTransition(c.id, 'complete')}>
          Complete
        </button>
      );
    }
    if (!isTerminal && canStaff && !busy && confirmCancelId !== c.id) {
      buttons.push(
        <button key="cancel" type="button" className="btn-small btn-danger"
          onClick={() => setConfirmCancelId(c.id)}>
          Cancel
        </button>
      );
    }
    if (isDraft && canManage && !busy) {
      buttons.push(
        <button key="edit" type="button" className="btn-small btn-ghost"
          onClick={() => { location.hash = `#/lifecycle/new?edit=${c.id}`; }}>
          Edit Draft
        </button>
      );
    }

    return buttons.length ? (
      <div className="row-gap" style={{ gap: 'var(--sp-05)' }}>{buttons}</div>
    ) : <span className="muted small">—</span>;
  };

  const columns = [
    {
      key: 'case_number', label: 'Case Number',
      render: (r) => <a href={`#/lifecycle/${r.id}`}>{r.case_number}</a>,
    },
    {
      key: 'employee', label: 'Employee',
      render: (r) => r.employee_email || r.employee_id || `User #${r.employee}`,
    },
    {
      key: 'department', label: 'Department',
      render: (r) => r.department ? String(r.department) : '—',
    },
    {
      key: 'status', label: 'Status',
      render: (r) => <Badge kind="status" value={r.status} />,
    },
    {
      key: 'priority', label: 'Priority',
      render: (r) => <Badge kind="priority" value={r.priority} />,
    },
    {
      key: 'coordinator', label: 'Coordinator',
      render: (r) => r.assigned_coordinator ? String(r.assigned_coordinator) : 'Unassigned',
    },
    {
      key: 'planned_date', label: 'Planned Date',
      render: (r) => formatDate(r.planned_date),
    },
    {
      key: 'effective_date', label: 'Effective Date',
      render: (r) => formatDate(r.effective_date),
    },
    {
      key: 'completion_target', label: 'Completion Target',
      render: (r) => formatDate(r.completion_target),
    },
    {
      key: 'progress', label: 'Progress',
      render: (r) => <span>{r.checklist_progress != null ? `${Math.round(r.checklist_progress)}%` : '0%'}</span>,
    },
    {
      key: 'overdue_tasks', label: 'Overdue Tasks',
      render: (r) => r.overdue_tasks > 0 ? <span className="badge badge-red">{r.overdue_tasks}</span> : String(r.overdue_tasks),
    },
    {
      key: 'updated', label: 'Updated',
      render: (r) => formatDateTime(r.updated_at),
    },
    {
      key: 'actions', label: 'Actions',
      render: (r) => rowActions(r),
    },
  ];

  if (loading) {
    return (
      <div className="lifecycle-cases">
        <PageHeader title={CASE_TYPE_LABELS[caseType] ?? 'Cases'} />
        <div role="status" aria-label="Loading">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="skeleton-row">
              <span className="sk-cell" style={{ width: '14%' }} /><span className="sk-cell" style={{ width: '26%' }} />
              <span className="sk-cell" style={{ width: '14%' }} /><span className="sk-cell" style={{ width: '12%' }} />
              <span className="sk-cell" style={{ width: '10%' }} /><span className="sk-cell" style={{ width: '12%' }} />
              <span className="sk-cell" style={{ width: '12%' }} /><span className="sk-cell" style={{ width: '10%' }} />
              <span className="sk-cell" style={{ width: '10%' }} /><span className="sk-cell" style={{ width: '10%' }} />
              <span className="sk-cell" style={{ width: '10%' }} /><span className="sk-cell" style={{ width: '12%' }} />
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (error && !items.length) {
    return (
      <div className="lifecycle-cases">
        <PageHeader title={CASE_TYPE_LABELS[caseType] ?? 'Cases'} />
        <div className="error-summary" role="alert">{error}</div>
        <button type="button" className="btn-secondary" onClick={doRetry}>Retry</button>
      </div>
    );
  }
  return (
    <div className="lifecycle-cases">
      <PageHeader
        title={CASE_TYPE_LABELS[caseType] ?? 'Cases'}
        sub={`${count} case${count === 1 ? '' : 's'}`}
        actions={
          <div className="row-gap" style={{ alignItems: 'center', gap: 'var(--sp-1)' }}>
            {canManage && !isEmpView ? (
              <a className="btn-primary" href="#/lifecycle/new">+ Create Case</a>
            ) : null}
          </div>
        }
      />
      {error && <ErrorSummary parsed={{ global: error }} />}

      <section className="section" style={{ marginTop: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <h4 className="section-title">Filters</h4>
        <div className="filter-bar" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)', alignItems: 'end' }}>
          <Field label="Status">
            <select className="input" value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value, page: 1 }))}>
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{CASE_STATUS_LABELS[s] ?? s}</option>)}
            </select>
          </Field>
          <Field label="Priority">
            <select className="input" value={filters.priority} onChange={(e) => setFilters((f) => ({ ...f, priority: e.target.value, page: 1 }))}>
              <option value="">All priorities</option>
              {PRIORITY_OPTIONS.map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p] ?? p}</option>)}
            </select>
          </Field>
          {!isEmpView && (
            <Field label="Employee">
              <UserSelect value={filters.employee} onChange={(id) => setFilters((f) => ({ ...f, employee: id != null ? Number(id) : '', page: 1 }))} />
            </Field>
          )}
          <Field label="Department">
            <select className="input" value={filters.department} onChange={(e) => setFilters((f) => ({ ...f, department: e.target.value, page: 1 }))}>
              <option value="">All departments</option>
            </select>
          </Field>
          <Field label="Blocked">
            <select className="input" value={filters.blocked} onChange={(e) => setFilters((f) => ({ ...f, blocked: e.target.value, page: 1 }))}>
              <option value="">All</option>
              <option value="true">Blocked only</option>
              <option value="false">Not blocked</option>
            </select>
          </Field>
          <Field label="Overdue">
            <select className="input" value={filters.overdue} onChange={(e) => setFilters((f) => ({ ...f, overdue: e.target.value, page: 1 }))}>
              <option value="">All</option>
              <option value="true">Overdue only</option>
              <option value="false">Not overdue</option>
            </select>
          </Field>
          <Field label="Source">
            <select className="input" value={filters.source} onChange={(e) => setFilters((f) => ({ ...f, source: e.target.value, page: 1 }))}>
              <option value="">All sources</option>
              {SOURCE_OPTIONS.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
          </Field>
          <Field label="Search">
            <input className="input" value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value, page: 1 }))} placeholder="Case number, employee…" />
          </Field>
        </div>
      </section>

      <DataTable
        columns={columns}
        rows={items}
        keyOf={(r) => r.case_number || String(r.id)}
        emptyTitle="No cases"
        emptyHint={isEmpView ? 'You have no lifecycle cases.' : 'No cases match the current filters.'}
      />

      <Pager
        count={count}
        hasPrev={hasPrev}
        hasNext={hasNext}
        onPrev={() => setPage((p) => p - 1)}
        onNext={() => setPage((p) => p + 1)}
        busy={loading}
        pageLabel={`Page ${page} of ${Math.max(1, Math.ceil(count / pageSize))}`}
      />
      {confirmCancelId && (
        <ConfirmDialog
          title="Cancel case?"
          message={`Canceling ${items.find((c) => c.id === confirmCancelId)?.case_number || 'this case'} will mark it as cancelled.`}
          confirmLabel="Cancel case" danger busy={deleteBusy}
          onConfirm={doCancel}
          onCancel={() => setConfirmCancelId(null)}
        />
      )}
    </div>
  );
}

