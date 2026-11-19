import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, Field, Input, LoadingRows, PageHeader, Pager, Select,
} from './components';
import { parseApiError } from './api-utils';
import {
  CI_LIFECYCLE_LABELS,
  CI_STATUS_LABELS,
  CRITICALITY_LABELS,
  ENVIRONMENT_LABELS,
  MONITORING_STATE_LABELS,
  SOURCE_LABELS,
  buildCIListUrl,
  formatDateTime,
  safeResults,
} from './cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS } from './cmdb';
import { GlobalRelationshipsPage } from './cmdb-relationships';

function readHashParams() {
  const raw = window.location.hash.split('?')[1] || '';
  const sp = new URLSearchParams(raw);
  const obj = {};
  sp.forEach((v, k) => { obj[k] = v; });
  return obj;
}

function writeHashParams(next) {
  const params = new URLSearchParams();
  Object.entries(next).forEach(([k, v]) => {
    if (v !== '' && v != null) params.set(k, String(v));
  });
  const qs = params.toString();
  window.location.hash = qs ? `#/cmdb/items?${qs}` : '#/cmdb/items';
}

export function CmdbItemsList() {
  const routePath = window.location.hash.split('?')[0];
  if (routePath === '#/cmdb/relationships') {
    return <GlobalRelationshipsPage />;
  }
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [types, setTypes] = useState([]);
  const [draft, setDraft] = useState({});
  const [params, setParams] = useState(() => ({ page: '1', ...readHashParams() }));

  useEffect(() => {
    const sync = () => setParams({ page: '1', ...readHashParams() });
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    setDraft({
      search: params.search || '',
      status: params.status || '',
      criticality: params.criticality || '',
      environment: params.environment || '',
      type: params.type || '',
      source: params.source || '',
      verified: params.verified || '',
    });
  }, [params.search, params.status, params.criticality, params.environment, params.type, params.source, params.verified]);

  useEffect(() => {
    let cancelled = false;
    api.get('/cmdb/types/')
      .then((r) => { if (!cancelled) setTypes(safeResults(r.data?.results ?? r.data)); })
      .catch(() => { if (!cancelled) setTypes([]); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    const q = { ...params, page: params.page || '1' };
    api.get(`${CMDB_API_CONTRACT.ciList.endpoint}${buildCIListUrl(q)}`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data;
        const rows = Array.isArray(data) ? data : safeResults(data?.results ?? []);
        setItems(rows);
        setCount(Array.isArray(data) ? rows.length : (data?.count ?? rows.length));
      })
      .catch((e) => {
        if (cancelled) return;
        setError(parseApiError(e).global || 'Could not load configuration items.');
        setItems([]);
        setCount(0);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [params]);

  const typeById = useMemo(() => {
    const m = new Map();
    types.forEach((t) => m.set(String(t.id), t));
    return m;
  }, [types]);

  const canCreate = CMDB_PERMISSIONS.canCreateCI(role);
  const canView = CMDB_PERMISSIONS.canViewCIList(role);

  const page = Math.max(1, parseInt(params.page || '1', 10) || 1);
  const pageSize = Array.isArray(items) && !readHashParams().page && count === items.length ? items.length || 1 : 50;
  const totalPages = Math.max(1, Math.ceil((count || 0) / 50));

  const applyFilters = (e) => {
    e?.preventDefault?.();
    writeHashParams({ ...draft, page: 1 });
  };

  const clearFilters = () => {
    writeHashParams({ page: 1 });
  };

  const goToPage = (nextPage) => {
    writeHashParams({ ...params, page: nextPage });
  };

  const columns = useMemo(() => ([
    {
      key: 'ci_number',
      label: 'CI Number',
      render: (row) => (
        <a href={`#/cmdb/items/${row.id}`}>{row.ci_number || `CI #${row.id}`}</a>
      ),
    },
    {
      key: 'name',
      label: 'Name',
      render: (row) => (
        <a href={`#/cmdb/items/${row.id}`}>{row.name || '—'}</a>
      ),
    },
    {
      key: 'ci_type',
      label: 'Type',
      render: (row) => row.ci_type_name || typeById.get(String(row.ci_type))?.name || row.ci_type || '—',
    },
    {
      key: 'status',
      label: 'Status',
      render: (row) => <Badge kind="status" value={row.status} label={CI_STATUS_LABELS[row.status] || row.status || '—'} />,
    },
    {
      key: 'lifecycle_state',
      label: 'Lifecycle',
      render: (row) => CI_LIFECYCLE_LABELS[row.lifecycle_state] || row.lifecycle_state || '—',
    },
    {
      key: 'criticality',
      label: 'Criticality',
      render: (row) => <Badge kind="priority" value={row.criticality} label={CRITICALITY_LABELS[row.criticality] || row.criticality || '—'} />,
    },
    {
      key: 'environment',
      label: 'Environment',
      render: (row) => ENVIRONMENT_LABELS[row.environment] || row.environment || '—',
    },
    {
      key: 'department',
      label: 'Department',
      render: (row) => row.department_name || row.department || '—',
    },
    { key: 'location', label: 'Location', render: (row) => row.location || '—' },
    { key: 'owner', label: 'Owner', render: (row) => row.owner_username || row.owner || '—' },
    {
      key: 'last_verified_at',
      label: 'Last Verified',
      render: (row) => (row.last_verified_at ? formatDateTime(row.last_verified_at) : 'Never'),
    },
    {
      key: 'updated_at',
      label: 'Updated',
      render: (row) => (row.updated_at ? formatDateTime(row.updated_at) : '—'),
    },
  ]), [typeById]);

  if (role === 'employee' || !canView) {
    return <div className="error-summary" role="alert">You do not have permission to view configuration items.</div>;
  }

  return (
    <div>
      <PageHeader
        title="Configuration Items"
        sub={`${count} item${count === 1 ? '' : 's'} in CMDB`}
        actions={(
          <>
            <a className="btn-small" href="#/cmdb">Dashboard</a>
            <a className="btn-small" href="#/cmdb/types">CI Types</a>
            <a className="btn-small" href="#/cmdb/baselines">Baselines</a>
            <a className="btn-small" href="#/cmdb/drift">Drift</a>
            <a className="btn-small" href="#/cmdb/verification">Verification</a>
            <a className="btn-small" href="#/cmdb/reports">Reports</a>
            {canCreate && <a className="btn-primary" href="#/cmdb/items/new">+ New CI</a>}
          </>
        )}
      />

      <form className="panel panel-pad" onSubmit={applyFilters} style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Search and filter</h3>
        <div className="row-gap" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Field label="Search">
            <Input
              value={draft.search || ''}
              onChange={(e) => setDraft({ ...draft, search: e.target.value })}
              placeholder="CI number, name, hostname, serial..."
              aria-label="Search configuration items"
            />
          </Field>
          <Field label="Type">
            <Select value={draft.type || ''} onChange={(e) => setDraft({ ...draft, type: e.target.value })} aria-label="Filter by type">
              <option value="">All types</option>
              {types.map((t) => <option key={t.id} value={t.id}>{t.name || t.code}</option>)}
            </Select>
          </Field>
          <Field label="Status">
            <Select value={draft.status || ''} onChange={(e) => setDraft({ ...draft, status: e.target.value })} aria-label="Filter by status">
              <option value="">All statuses</option>
              {Object.entries(CI_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Criticality">
            <Select value={draft.criticality || ''} onChange={(e) => setDraft({ ...draft, criticality: e.target.value })} aria-label="Filter by criticality">
              <option value="">All criticalities</option>
              {Object.entries(CRITICALITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Environment">
            <Select value={draft.environment || ''} onChange={(e) => setDraft({ ...draft, environment: e.target.value })} aria-label="Filter by environment">
              <option value="">All environments</option>
              {Object.entries(ENVIRONMENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Source">
            <Select value={draft.source || ''} onChange={(e) => setDraft({ ...draft, source: e.target.value })} aria-label="Filter by source">
              <option value="">All sources</option>
              {Object.entries(SOURCE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Verified">
            <Select value={draft.verified || ''} onChange={(e) => setDraft({ ...draft, verified: e.target.value })} aria-label="Filter by verification">
              <option value="">Any</option>
              <option value="true">Verified</option>
              <option value="false">Not verified</option>
            </Select>
          </Field>
        </div>
        <div className="row-gap" style={{ marginTop: 12 }}>
          <button type="submit" className="btn-primary">Apply filters</button>
          <button type="button" className="btn-ghost" onClick={clearFilters}>Clear</button>
        </div>
      </form>

      {error && <div className="error-summary" role="alert">{error}</div>}

      {loading ? (
        <div className="panel panel-pad"><LoadingRows n={8} /></div>
      ) : items.length === 0 ? (
        <EmptyState
          title="No configuration items found"
          hint={Object.keys(params).some((k) => k !== 'page' && params[k]) ? 'Try adjusting or clearing your filters.' : 'Create a configuration item to start building the CMDB.'}
          action={canCreate ? <a className="btn-primary" href="#/cmdb/items/new">Create CI</a> : null}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={items}
            keyOf={(r) => r.id ?? r.ci_number}
            emptyTitle="No configuration items found."
            emptyHint="Adjust filters to find CIs."
          />
          <div className="panel panel-pad" style={{ marginTop: 12 }}>
            <Pager
              count={count}
              hasNext={page < totalPages}
              hasPrev={page > 1}
              onPrev={() => goToPage(page - 1)}
              onNext={() => goToPage(page + 1)}
              busy={loading}
              pageLabel={count ? `Page ${page} of ${totalPages}` : ''}
            />
          </div>
        </>
      )}
    </div>
  );
}