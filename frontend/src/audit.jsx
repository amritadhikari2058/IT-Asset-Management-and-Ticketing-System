import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { DataTable, LoadingRows, PageHeader, Pager } from './components';
import { fetchPage } from './api-utils';

const ACTIONS = [
  '', 'create', 'update', 'soft_delete', 'restore', 'hard_delete',
  'bulk_create', 'bulk_update', 'bulk_soft_delete', 'status_change',
  'assignment', 'deactivate', 'reactivate', 'retire', 'note',
];

const ACTION_LABELS = {
  create: 'Created',
  update: 'Updated',
  soft_delete: 'Soft-deleted',
  restore: 'Restored',
  hard_delete: 'Permanently deleted',
  bulk_create: 'Bulk created',
  bulk_update: 'Bulk updated',
  bulk_soft_delete: 'Bulk soft-deleted',
  status_change: 'Status changed',
  assignment: 'Assignment changed',
  deactivate: 'Deactivated',
  reactivate: 'Reactivated',
  retire: 'Retired',
  note: 'Note added',
};

const ENTITY_LABELS = {
  'tickets.Ticket': 'Ticket',
  'tickets.TicketCategory': 'Ticket category',
  'tickets.TicketAttachment': 'Ticket attachment',
  'assets.Asset': 'Asset',
  'assets.AssetCategory': 'Asset category',
  'assets.AssetAttachment': 'Asset attachment',
  'accounts.User': 'Employee',
  'accounts.Department': 'Department',
  'common.Notification': 'Notification',
};

export function AuditLogPage() {
  const { isAdmin } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [pageSize, setPageSize] = useState(20);
  const [f, setF] = useState({ action: '', entity_type: '', date_from: '', date_to: '' });

  const buildUrl = (over = {}) => {
    const p = new URLSearchParams();
    const merged = { ...f, ...over };
    for (const k of ['action', 'entity_type', 'date_from', 'date_to']) {
      if (merged[k]) p.set(k, merged[k]);
    }
    p.set('page_size', String(pageSize));
    // Client-side guard: an end date before the start date can never match.
    if (merged.date_from && merged.date_to && merged.date_to < merged.date_from) {
      return null;
    }
    const qs = p.toString();
    return `/common/audit-logs/${qs ? `?${qs}` : ''}`;
  };

  const loadUrl = async (url) => {
    if (!url) {
      setListError('End date cannot be earlier than start date.');
      return;
    }
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch (e) {
      setListError(
        e?.response?.data?.action?.join(' ')
        || e?.response?.data?.date_from?.join(' ')
        || e?.response?.data?.date_to?.join(' ')
        || 'Could not load audit log.',
      );
    } finally {
      setLoading(false);
    }
  };

  const applyFilters = (patch) => {
    const merged = { ...f, ...patch };
    setF(merged);
    const p = new URLSearchParams();
    for (const k of ['action', 'entity_type', 'date_from', 'date_to']) {
      if (merged[k]) p.set(k, merged[k]);
    }
    p.set('page_size', String(pageSize));
    if (merged.date_from && merged.date_to && merged.date_to < merged.date_from) {
      setListError('End date cannot be earlier than start date.');
      return;
    }
    const qs = p.toString();
    loadUrl(`/common/audit-logs/${qs ? `?${qs}` : ''}`);
  };

  const resetFilters = () => {
    const cleared = { action: '', entity_type: '', date_from: '', date_to: '' };
    setF(cleared);
    loadUrl(`/common/audit-logs/?page_size=${pageSize}`);
  };

  const changePageSize = (value) => {
    const size = Number(value) || 20;
    setPageSize(size);
    const p = new URLSearchParams();
    for (const k of ['action', 'entity_type', 'date_from', 'date_to']) {
      if (f[k]) p.set(k, f[k]);
    }
    p.set('page_size', String(size));
    loadUrl(`/common/audit-logs/${p.toString() ? `?${p}` : ''}`);
  };

  useEffect(() => {
    if (isAdmin) loadUrl('/common/audit-logs/');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isAdmin) {
    return (
      <div>
        <PageHeader title="Audit log" />
        <div className="error-summary" role="alert">
          System administrators only.
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Audit log"
        sub={count != null ? `${count} entries` : 'Append-only record of consequential actions.'}
      />
      <div className="filter-bar" role="search">
        <select
          className="input" value={f.action}
          onChange={(e) => applyFilters({ action: e.target.value })}
          aria-label="Filter by action"
        >
          <option value="">All actions</option>
          {ACTIONS.filter(Boolean).map((a) => <option key={a} value={a}>{ACTION_LABELS[a] ?? a}</option>)}
        </select>
        <input
          className="input" value={f.entity_type}
          onChange={(e) => applyFilters({ entity_type: e.target.value })}
          placeholder="Entity type, e.g. tickets.Ticket" aria-label="Filter by entity type"
        />
        <input
          className="input" type="date" value={f.date_from}
          onChange={(e) => applyFilters({ date_from: e.target.value })}
          aria-label="Start date"
        />
        <input
          className="input" type="date" value={f.date_to}
          onChange={(e) => applyFilters({ date_to: e.target.value })}
          aria-label="End date"
        />
        <select className="input" value={pageSize} onChange={(e) => changePageSize(e.target.value)} aria-label="Page size">
          {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n} per page</option>)}
        </select>
        <button type="button" className="btn-ghost" onClick={resetFilters}>Reset</button>
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl(buildUrl())}>Retry</button></div></div>
          : (<>
            <DataTable
              columns={[
                { key: 'timestamp', label: 'Time', render: (a) => a.timestamp ? new Date(a.timestamp).toLocaleString() : '—' },
                { key: 'actor', label: 'Actor', render: (a) => <span className="ellipsis" title={a.actor_email ?? ''}>{a.actor_email ?? '—'}</span> },
                { key: 'action', label: 'Action', render: (a) => ACTION_LABELS[a.action] ?? a.action },
                { key: 'entity_type', label: 'Entity', render: (a) => <span className="ellipsis" title={a.entity_type ?? ''}>{ENTITY_LABELS[a.entity_type] ?? a.entity_type}</span> },
                { key: 'object_id', label: 'Object' },
                { key: 'object_repr', label: 'Summary', render: (a) => <span className="ellipsis" title={a.object_repr || a.reason || ''}>{a.object_repr || a.reason || '—'}</span> },
              ]}
              rows={items}
              keyOf={(a) => a.id}
              emptyTitle="No audit entries match."
              emptyHint="Adjust or reset the filters."
            />
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
    </div>
  );
}
