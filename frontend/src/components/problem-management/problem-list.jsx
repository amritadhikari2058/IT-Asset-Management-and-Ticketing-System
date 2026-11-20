import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, Option, PageHeader, Pager, Select } from '../../components';
import { problemList } from '../../services/problem-management';
import { PRIORITY_CHOICES, PROBLEM_STATUS_CHOICES, PROBLEM_TYPE_CHOICES } from '../../types/problem-management';

const EMPTY_FILTERS = {
  status: '',
  priority: '',
  problem_type: '',
  owner: '',
  service: '',
  category: '',
  search: '',
  is_open: false,
  // Recurrence filter: show problems with linked tickets above this count
  min_ticket_count: '',
};

const toLabel = (value) => String(value).replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());

function statusKind(status) {
  if (status === 'resolved' || status === 'closed') return 'status-success';
  if (status === 'rejected') return 'status-danger';
  if (status === 'cancelled') return 'status-muted';
  return 'status-warning';
}

export function ProblemList() {
  const { isStaff } = useAuth();
  // Page-size preference persisted in localStorage; fall back to DRF default 20.
  const [pageSize, setPageSize] = useState(() => {
    if (typeof window === 'undefined') return 20;
    try {
      const saved = window.localStorage.getItem('itdesk.pageSize');
      return saved ? Number(saved) : 20;
    } catch {
      return 20;
    }
  });
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState([]);
  const [count, setCount] = useState(null);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrev, setHasPrev] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Stable serialization: blank filters are dropped and keys are ordered, so
  // the same filter state always produces exactly one query shape.
  const queryKey = useMemo(() => {
    const entries = Object.entries(filters)
      .filter(([, value]) => value !== '' && value !== false && value != null)
      .sort(([a], [b]) => a.localeCompare(b));
    return JSON.stringify(entries);
  }, [filters]);

  useEffect(() => {
    let active = true;
    const params = Object.fromEntries(JSON.parse(queryKey));
    setLoading(true);
    setError('');
    problemList({ ...params, page, page_size: pageSize })
      .then((data) => {
        if (!active) return;
        const result = Array.isArray(data) ? { results: data, count: data.length } : data;
        setRows(result.results ?? []);
        setCount(result.count ?? null);
        setHasNext(Boolean(result.next));
        setHasPrev(Boolean(result.previous));
      })
      .catch(() => { if (active) setError('Could not load problems.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [queryKey, page]);

  // Reset to page 1 when page size changes
  useEffect(() => {
    setPage(1);
  }, [pageSize]);

  const update = (patch) => {
    setPage(1);
    setFilters((f) => ({ ...f, ...patch }));
  };

  const columns = [
    {
      key: 'problem_number',
      label: 'Problem',
      render: (r) => <Link className="row-title" to={`/problem-management/${r.id}`}>{r.problem_number}</Link>,
    },
    { key: 'title', label: 'Title' },
    { key: 'status', label: 'Status', render: (r) => <Badge kind={statusKind(r.status)} value={r.status} /> },
    { key: 'priority', label: 'Priority', render: (r) => <Badge kind={`status-${r.priority || 'muted'}`} value={r.priority} /> },
    { key: 'problem_type', label: 'Type', render: (r) => (r.problem_type ? toLabel(r.problem_type) : '—') },
    { key: 'owner_username', label: 'Owner', render: (r) => r.owner_username || '—' },
    { key: 'service_name', label: 'Service', render: (r) => r.service_name || '—' },
    { key: 'category_name', label: 'Category', render: (r) => r.category_name || '—' },
    {
      key: 'linked_ticket_count',
      label: 'Tickets',
      render: (r) => {
        const count = r.linked_ticket_count || 0;
        if (count === 0) return <span className="muted">—</span>;
        return <span>{count}</span>;
      },
    },
    {
      key: 'recurrence_risk',
      label: 'Risk',
      render: (r) => {
        const count = r.linked_ticket_count || 0;
        if (count === 0) return <span className="muted">—</span>;
        if (count >= 5) return <Tag kind="critical">High recurrence</Tag>;
        if (count >= 3) return <Tag kind="warning">Medium recurrence</Tag>;
        if (count >= 1) return <Tag kind="info">Low recurrence</Tag>;
        return <span className="muted">—</span>;
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="Problems"
        sub={count != null ? `${count} ${count === 1 ? 'problem' : 'problems'} in scope` : undefined}
        actions={isStaff ? <Link className="btn-primary" to="/problem-management/new">Create Problem</Link> : null}
      />
      <div className="filter-bar row-gap">
        <Field label="Status">
          <Select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            <Option value="">All</Option>
            {PROBLEM_STATUS_CHOICES.map((s) => <Option key={s} value={s}>{toLabel(s)}</Option>)}
          </Select>
        </Field>
        <Field label="Priority">
          <Select value={filters.priority} onChange={(e) => update({ priority: e.target.value })}>
            <Option value="">All</Option>
            {PRIORITY_CHOICES.map((p) => <Option key={p} value={p}>{toLabel(p)}</Option>)}
          </Select>
        </Field>
        <Field label="Problem type">
          <Select value={filters.problem_type} onChange={(e) => update({ problem_type: e.target.value })}>
            <Option value="">All</Option>
            {PROBLEM_TYPE_CHOICES.map((t) => <Option key={t} value={t}>{toLabel(t)}</Option>)}
          </Select>
        </Field>
        <Field label="Owner">
          <Input value={filters.owner} onChange={(e) => update({ owner: e.target.value })} placeholder="Owner id" />
        </Field>
        <Field label="Service">
          <Input value={filters.service} onChange={(e) => update({ service: e.target.value })} placeholder="Service id" />
        </Field>
        <Field label="Category">
          <Input value={filters.category} onChange={(e) => update({ category: e.target.value })} placeholder="Category id" />
        </Field>
        <Field label="Search">
          <Input placeholder="Search…" value={filters.search} onChange={(e) => update({ search: e.target.value })} />
        </Field>
        <label className="check-inline">
          <input
            type="checkbox"
            checked={filters.is_open}
            onChange={(e) => update({ is_open: e.target.checked })}
          />
          {' '}Open only
        </label>
        <Button kind="ghost" onClick={() => { setPage(1); setFilters(EMPTY_FILTERS); }}>Reset</Button>
      </div>

      {error && <div className="error-summary" role="alert">{error}</div>}
      {loading
        ? <p className="page-loading" role="status">Loading problems…</p>
        : (
          <DataTable
            columns={columns}
            rows={rows}
            keyOf={(r) => r.id}
            emptyTitle="No problems found"
            emptyHint="Adjust the filters or create the first problem."
          />
        )}
      <PageSizeSelector value={pageSize} onChange={setPageSize} />
      <Pager
        count={count}
        hasNext={hasNext}
        hasPrev={hasPrev}
        busy={loading}
        pageLabel={count != null ? `Page ${page}` : ''}
        onPrev={() => setPage((p) => Math.max(1, p - 1))}
        onNext={() => setPage((p) => p + 1)}
      />
    </div>
  );
}
