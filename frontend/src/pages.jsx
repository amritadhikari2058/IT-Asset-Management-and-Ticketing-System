import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, CategorySelect, ConfirmDialog, DataTable, DepartmentSelect, EmptyState,
  Field, LoadingRows, Modal, PageHeader, Pager, TableControls, UserSelect,
  useSort, useTableColumns,
} from './components';
import { fetchPage, fieldMsg, parseApiError } from './api-utils';
import { AssetBulkCreateModal, EmployeeCreateModal, EmployeeImportModal, TicketBulkCreateModal } from './bulk';

const TICKET_STATUSES = ['', 'open', 'in_progress', 'resolved', 'closed', 'reopened', 'archived'];
const TICKET_PRIORITIES = ['', 'low', 'medium', 'high', 'critical'];
const ASSET_STATUSES = ['', 'available', 'assigned', 'in_repair', 'retired', 'lost'];

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('admin@local');
  const [password, setPassword] = useState('admin12345');
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try { await login(email, password); location.hash = '#/tickets'; }
    catch { setErr('Login failed. Is the backend running + seeded?'); }
  };
  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-mark">IT</span>
          <h2>Service Desk</h2>
        </div>
        <p className="login-sub">Sign in with your organization account.</p>
        <form onSubmit={submit}>
          <div className="form-field">
            <label className="form-label" htmlFor="login-email">Email</label>
            <input id="login-email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="username" />
          </div>
          <div className="form-field">
            <label className="form-label" htmlFor="login-password">Password</label>
            <input id="login-password" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" autoComplete="current-password" />
          </div>
          {err && <div className="error-summary" role="alert">{err}</div>}
          <button type="submit" className="btn-primary">Log in</button>
        </form>
        <p className="login-hint">Seeded: admin@local / manager@local / support@local / employee@local</p>
      </div>
    </div>
  );
}

export function Tickets() {
  const { canCreateTickets, isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [sel, setSel] = useState(new Set());
  const [report, setReport] = useState(null);
  const [reportError, setReportError] = useState('');
  const [showBulkCreate, setShowBulkCreate] = useState(false);
  const [f, setF] = useState({ q: '', status: '', priority: '', category: '', department: '' });
  const [sort, changeSort, orderingParam] = useSort();
  const [reportDateFrom, setReportDateFrom] = useState('');
  const [reportDateTo, setReportDateTo] = useState('');

  const TICKET_COLUMNS = [
    { key: 'id', label: 'ID' },
    { key: 'title', label: 'Subject', render: (t) => <a className="row-title" href={`#/tickets/${t.id}`}>{t.title}</a> },
    { key: 'status', label: 'Status', sortable: 'status', render: (t) => <Badge kind="status" value={t.status} /> },
    { key: 'priority', label: 'Priority', sortable: 'priority', render: (t) => <Badge kind="priority" value={t.priority} /> },
    { key: 'category', label: 'Category', render: (t) => t.category_name ?? '-' },
    { key: 'assignee', label: 'Assignee', render: (t) => t.assignee_email ? <span className="ellipsis" title={t.assignee_email}>{t.assignee_email}</span> : '-' },
    { key: 'requester', label: 'Requester', render: (t) => t.requester_email ? <span className="ellipsis" title={t.requester_email}>{t.requester_email}</span> : '-' },
    { key: 'department', label: 'Department', render: (t) => t.department_name ?? '-' },
    { key: 'asset', label: 'Asset', render: (t) => t.asset_tag ? <span className="ellipsis" title={t.asset_tag}>{t.asset_tag}</span> : (t.asset ? `#${t.asset}` : '-') },
    { key: 'description', label: 'Description', render: (t) => <span className="ellipsis" title={t.description}>{t.description || '-'}</span> },
    { key: 'on_behalf_reason', label: 'On-behalf reason', render: (t) => <span className="ellipsis" title={t.on_behalf_reason}>{t.on_behalf_reason || '-'}</span> },
    { key: 'resolution_notes', label: 'Resolution notes', render: (t) => <span className="ellipsis" title={t.resolution_notes}>{t.resolution_notes || '-'}</span> },
    { key: 'created', label: 'Created', sortable: 'created_at', render: (t) => t.created_at ? new Date(t.created_at).toLocaleDateString() : '-' },
    { key: 'updated', label: 'Updated', render: (t) => t.updated_at ? new Date(t.updated_at).toLocaleDateString() : '-' },
    { key: 'resolved_at', label: 'Resolved', render: (t) => t.resolved_at ? new Date(t.resolved_at).toLocaleString() : '-' },
    { key: 'closed_at', label: 'Closed', render: (t) => t.closed_at ? new Date(t.closed_at).toLocaleString() : '-' },
  ];
  const { visibleColumns: visibleTicketColumns, toggleColumn: toggleTicketColumn, resetColumns: resetTicketColumns, tableVisible: ticketTableVisible, toggleTable: toggleTicketTable } = useTableColumns(
    TICKET_COLUMNS.map((c) => c.key),
    ['title', 'status', 'priority', 'category', 'assignee', 'department', 'created'],
  );
  const ticketColumns = TICKET_COLUMNS.filter((c) => visibleTicketColumns.has(c.key));

  const buildUrl = (over = {}, sortOverride) => {
    const p = new URLSearchParams();
    const merged = { ...f, ...over };
    for (const k of ['q', 'status', 'priority', 'category', 'department']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam(sortOverride);
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    return `/tickets/${qs ? `?${qs}` : ''}`;
  };
  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setListError('Could not load tickets.');
    } finally {
      setLoading(false);
    }
  };
  const applyFilters = (patch) => {
    const merged = { ...f, ...patch };
    setF(merged);
    setSel(new Set());
    const p = new URLSearchParams();
    for (const k of ['q', 'status', 'priority', 'category', 'department']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/tickets/${qs ? `?${qs}` : ''}`);
  };
  const changeTicketSort = (field) => {
    const next = changeSort(field);
    setSel(new Set());
    loadUrl(buildUrl({}, next));
  };
  const loadReport = async (over = {}) => {
    const dateFrom = over.date_from !== undefined ? over.date_from : reportDateFrom;
    const dateTo = over.date_to !== undefined ? over.date_to : reportDateTo;
    if (dateFrom && dateTo && dateTo < dateFrom) {
      setReportError('Report end date cannot be earlier than start date.');
      return;
    }
    setReportError('');
    try {
      const p = new URLSearchParams();
      if (dateFrom) p.set('date_from', dateFrom);
      if (dateTo) p.set('date_to', dateTo);
      const qs = p.toString();
      const r = await api.get(`/tickets/reports/by-category/${qs ? `?${qs}` : ''}`);
      setReport(r.data.results);
    } catch {
      setReportError('Could not load the category report.');
    }
  };
  const resetReportDates = () => {
    setReportDateFrom('');
    setReportDateTo('');
    setReportError('');
    loadReport({ date_from: '', date_to: '' });
  };
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const bulk = async (changes) => {
    const ids = [...sel];
    if (!ids.length) return;
    try {
      const prev = await api.post('/tickets/bulk_update/', { ids, changes, preview: true });
      if (!confirm(`Affects ${prev.data.affected}. Invalid: ${prev.data.invalid_transitions.length}. Confirm?`)) return;
      const res = await api.post('/tickets/bulk_update/', { ids, changes, preview: false, confirm: true });
      alert(`OK ${res.data.summary.ok}, skipped ${res.data.summary.skipped}, failed ${res.data.summary.failed}`);
      setSel(new Set());
      loadUrl(buildUrl());
    } catch (e) {
      alert(e?.response?.status === 403
        ? 'Forbidden: bulk ticket updates require IT staff.'
        : (e?.response?.data?.detail || 'Bulk update failed.'));
    }
  };
  useEffect(() => { loadUrl('/tickets/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div>
      <PageHeader
        title="Tickets"
        sub={count != null ? `${count} in scope` : undefined}
        actions={<>
          {canCreateTickets && <a className="btn-primary" href="#/tickets/new">+ New ticket</a>}
          {canCreateTickets && <button type="button" className="btn-secondary" onClick={() => setShowBulkCreate(true)}>Bulk create…</button>}
        </>}
      />
      {showBulkCreate && <TicketBulkCreateModal onClose={() => setShowBulkCreate(false)} onCreated={() => loadUrl(buildUrl())} />}
      <div className="filter-bar" role="search">
        <input
          className="input grow" value={f.q} onChange={(e) => applyFilters({ q: e.target.value })}
          placeholder="Search subject or description…" aria-label="Search tickets"
        />
        <select className="input" value={f.status} onChange={(e) => applyFilters({ status: e.target.value })} aria-label="Filter by status">
          <option value="">All statuses</option>
          {TICKET_STATUSES.filter(Boolean).map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <select className="input" value={f.priority} onChange={(e) => applyFilters({ priority: e.target.value })} aria-label="Filter by priority">
          <option value="">All priorities</option>
          {TICKET_PRIORITIES.filter(Boolean).map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <DepartmentSelect value={f.department} onChange={(v) => applyFilters({ department: v ?? '' })} />
        <div className="filter-item">
          <CategorySelect kind="ticket" value={f.category} onChange={(v) => applyFilters({ category: v ?? '' })} />
        </div>
      </div>
      {isStaff && sel.size > 0 && (
        <div className="toolbar" role="toolbar" aria-label="Bulk actions">
          <span className="muted small">{sel.size} selected</span>
          <button type="button" className="btn-small" onClick={() => bulk({ status: 'closed' })}>Close selected</button>
          <button type="button" className="btn-small" onClick={() => bulk({ priority: 'high' })}>Set high priority</button>
          <button type="button" className="btn-small" onClick={() => setSel(new Set())}>Clear</button>
        </div>
      )}
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl(buildUrl())}>Retry</button></div></div>
          : (<>
            <TableControls tableVisible={ticketTableVisible} onToggleTable={toggleTicketTable} columns={TICKET_COLUMNS} visible={visibleTicketColumns} onToggleColumn={toggleTicketColumn} onReset={resetTicketColumns} />
            {ticketTableVisible ? (
              <DataTable
                columns={ticketColumns}
                rows={items}
                keyOf={(t) => t.id}
                selected={isStaff ? sel : undefined}
                onToggle={isStaff ? toggle : undefined}
                sort={sort}
                onSort={changeTicketSort}
                emptyTitle="No tickets match."
                emptyHint="Adjust the filters or create a new ticket."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
      <div className="panel">
        <div className="panel-title">
          <h4>Tickets by category</h4>
          <div className="panel-actions">
            <button type="button" className="btn-small" onClick={loadReport} disabled={loading}>
              {report ? 'Refresh' : 'Category report'}
            </button>
          </div>
        </div>
        <div className="panel-pad">
          <div className="report-filters">
            <input className="input input-date" type="date" value={reportDateFrom} onChange={(e) => setReportDateFrom(e.target.value)} aria-label="Report start date" />
            <input className="input input-date" type="date" value={reportDateTo} onChange={(e) => setReportDateTo(e.target.value)} aria-label="Report end date" />
            <button type="button" className="btn-secondary" onClick={() => loadReport()}>Apply dates</button>
            {(reportDateFrom || reportDateTo) && (
              <button type="button" className="btn-ghost" onClick={resetReportDates}>Reset</button>
            )}
          </div>
          {reportError && <div className="error-summary" role="alert">{reportError}</div>}
          {report && report.length === 0 && <EmptyState title="No data in scope." />}
          {report && report.map((r) => (
            <div key={r.id} className="report-row">
              <div className="row-gap">
                <b>{r.name}</b>
                <span className="muted small">total {r.total} — open {r.open_count} — closed {r.closed_count}</span>
                <span className="spacer" />
                <Badge kind="priority" value="high" /><span className="muted small">{r.high_count ?? 0}</span>
                <Badge kind="priority" value="critical" /><span className="muted small">{r.critical_count ?? 0}</span>
              </div>
              <div className="meter" style={{ marginTop: 6 }}>
                <div style={{ width: `${r.total ? (r.open_count / r.total) * 100 : 0}%` }} />
              </div>
            </div>))}
        </div>
      </div>
    </div>
  );
}

export function Assets() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [sel, setSel] = useState(new Set());
  const [retireBusy, setRetireBusy] = useState(false);
  const [f, setF] = useState({ q: '', status: '', category: '', department: '' });
  const [showBulkCreate, setShowBulkCreate] = useState(false);
  const [sort, changeSort, orderingParam] = useSort();
  const [photoPreviewUrl, setPhotoPreviewUrl] = useState(null);
  const [photoPreviewName, setPhotoPreviewName] = useState('');
  const [photoPreviewBusyId, setPhotoPreviewBusyId] = useState(null);
  const [photoPreviewError, setPhotoPreviewError] = useState('');

  const ASSET_COLUMNS = [
    { key: 'asset_tag', label: 'Tag', sortable: 'asset_tag', render: (a) => <a className="row-title" href={`#/assets/${a.id}`}>{a.asset_tag}</a> },
    { key: 'name', label: 'Name', sortable: 'name' },
    { key: 'status', label: 'Status', sortable: 'status', render: (a) => <Badge kind="status" value={a.status} /> },
    { key: 'category', label: 'Category', render: (a) => a.category_name ?? '-' },
    { key: 'department', label: 'Department', render: (a) => a.department_name ?? '-' },
    { key: 'assigned_to', label: 'Assignee', render: (a) => a.assigned_to_email ?? '-' },
    { key: 'location', label: 'Location', render: (a) => a.location || '-' },
    { key: 'serial_number', label: 'Serial', render: (a) => a.serial_number || '-' },
    { key: 'description', label: 'Description', render: (a) => a.description || '-' },
    { key: 'purchase_date', label: 'Purchased', render: (a) => a.purchase_date || '-' },
    { key: 'warranty_expiry', label: 'Warranty', render: (a) => a.warranty_expiry || '-' },
    { key: 'purchase_cost', label: 'Cost', render: (a) => a.purchase_cost ?? '-' },
    { key: 'created_at', label: 'Created', render: (a) => a.created_at ? new Date(a.created_at).toLocaleString() : '-' },
    { key: 'photo', label: 'Photo', render: (a) => a.photo_attachment_id ? (
      <button
        type="button" className="btn-small"
        onClick={() => openAssetPhotoPreview(a.photo_attachment_id)}
        disabled={photoPreviewBusyId === a.photo_attachment_id}
      >
        {photoPreviewBusyId === a.photo_attachment_id ? 'Loading…' : 'Preview'}
      </button>
    ) : '-' },
  ];
  const { visibleColumns: visibleAssetColumns, toggleColumn: toggleAssetColumn, resetColumns: resetAssetColumns, tableVisible: assetTableVisible, toggleTable: toggleAssetTable } = useTableColumns(
    ASSET_COLUMNS.map((c) => c.key),
    ['asset_tag', 'name', 'status', 'category', 'department', 'assigned_to', 'location'],
  );
  const assetColumns = ASSET_COLUMNS.filter((c) => visibleAssetColumns.has(c.key));

  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setListError('Could not load assets.');
    } finally {
      setLoading(false);
    }
  };
  const applyFilters = (patch) => {
    const merged = { ...f, ...patch };
    setF(merged);
    setSel(new Set());
    const p = new URLSearchParams();
    for (const k of ['q', 'status', 'category', 'department']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/assets/${qs ? `?${qs}` : ''}`);
  };
  const changeAssetSort = (field) => {
    const next = changeSort(field);
    setSel(new Set());
    const p = new URLSearchParams();
    for (const k of ['q', 'status', 'category', 'department']) {
      if (f[k] !== '' && f[k] != null) p.set(k, f[k]);
    }
    const ord = orderingParam(next);
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/assets/${qs ? `?${qs}` : ''}`);
  };
  useEffect(() => { loadUrl('/assets/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const retire = async () => {
    const ids = [...sel];
    if (!ids.length || retireBusy) return;
    if (!confirm(`Retire ${ids.length} selected asset(s)? History is kept.`)) return;
    setRetireBusy(true);
    try {
      for (const id of ids) await api.post(`/assets/${id}/retire/`);
      setSel(new Set());
      await loadUrl('/assets/');
    } catch {
      alert('Could not retire all selected assets.');
    } finally {
      setRetireBusy(false);
    }
  };
  const openAssetPhotoPreview = async (attachmentId) => {
    if (photoPreviewBusyId) return;
    setPhotoPreviewBusyId(attachmentId);
    setPhotoPreviewError('');
    try {
      const r = await api.get(`/assets/attachments/${attachmentId}/download/`, {
        responseType: 'blob',
      });
      const cd = r.headers?.['content-disposition'] || '';
      const m = cd.match(/filename="([^"]+)"/);
      const url = URL.createObjectURL(r.data);
      setPhotoPreviewUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      setPhotoPreviewName((m && m[1]) || `attachment-${attachmentId}`);
    } catch (e) {
      setPhotoPreviewError(
        e?.response?.status === 403
          ? 'You do not have permission to preview this photo.'
          : 'Photo preview failed.',
      );
    } finally {
      setPhotoPreviewBusyId(null);
    }
  };
  const closeAssetPhotoPreview = () => {
    setPhotoPreviewUrl((url) => {
      if (url) URL.revokeObjectURL(url);
      return null;
    });
    setPhotoPreviewName('');
    setPhotoPreviewError('');
  };
  return (
    <div>
      <PageHeader
        title="Assets"
        sub={count != null ? `${count} in inventory` : undefined}
        actions={<>
          {isStaff && <a className="btn-primary" href="#/assets/new">+ New asset</a>}
          {isStaff && <button type="button" className="btn-secondary" onClick={() => setShowBulkCreate(true)}>Bulk create…</button>}
        </>}
      />
      {showBulkCreate && <AssetBulkCreateModal onClose={() => setShowBulkCreate(false)} onImported={() => loadUrl('/assets/')} />}
      <div className="filter-bar" role="search">
        <input
          className="input grow" value={f.q} onChange={(e) => applyFilters({ q: e.target.value })}
          placeholder="Search tag, name, serial, department, or location…" aria-label="Search assets"
        />
        <select className="input" value={f.status} onChange={(e) => applyFilters({ status: e.target.value })} aria-label="Filter by status">
          <option value="">All statuses</option>
          {ASSET_STATUSES.filter(Boolean).map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <div className="filter-item">
          <CategorySelect kind="asset" value={f.category} onChange={(v) => applyFilters({ category: v ?? '' })} />
        </div>
        <div className="filter-item">
          <DepartmentSelect value={f.department} onChange={(v) => applyFilters({ department: v ?? '' })} />
        </div>
      </div>
      {isStaff && sel.size > 0 && (
        <div className="toolbar" role="toolbar" aria-label="Bulk actions">
          <span className="muted small">{sel.size} selected</span>
          <button type="button" className="btn-small" onClick={retire} disabled={retireBusy}>
            {retireBusy ? 'Retiring…' : 'Retire selected'}
          </button>
          <button type="button" className="btn-small" onClick={() => setSel(new Set())}>Clear</button>
        </div>
      )}
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl('/assets/')}>Retry</button></div></div>
          : (<>
            <TableControls tableVisible={assetTableVisible} onToggleTable={toggleAssetTable} columns={ASSET_COLUMNS} visible={visibleAssetColumns} onToggleColumn={toggleAssetColumn} onReset={resetAssetColumns} />
            {assetTableVisible ? (
              <DataTable
                columns={assetColumns}
                rows={items}
                keyOf={(a) => a.id}
                selected={isStaff ? sel : undefined}
                onToggle={isStaff ? toggle : undefined}
                sort={sort}
                onSort={changeAssetSort}
                emptyTitle="No assets match."
                emptyHint="Adjust the filters or add a new asset."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
      {photoPreviewError && <div className="field-error" role="alert">{photoPreviewError}</div>}
      {photoPreviewUrl && (
        <Modal title={photoPreviewName || 'Photo preview'} onClose={closeAssetPhotoPreview}>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <img
              src={photoPreviewUrl}
              alt={photoPreviewName || 'Photo preview'}
              style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain' }}
            />
          </div>
        </Modal>
      )}
      <p className="muted small">Assignment changes use the explicit assign workflow — bulk update rejects assignment keys.</p>
    </div>
  );
}

export function Categories() {
  const { isStaff } = useAuth();
  const [acats, setAcats] = useState([]);
  const [tcats, setTcats] = useState([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [name, setName] = useState('');
  const [which, setWhich] = useState('ticket');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [renaming, setRenaming] = useState(null); // {kind, cat}
  const [renameValue, setRenameValue] = useState('');
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState('');
  const [deleting, setDeleting] = useState(null); // {kind, cat}
  const [deleteBusy, setDeleteBusy] = useState(false);
  const load = async () => {
    setLoading(true);
    setListError('');
    try {
      setAcats((await api.get('/assets/categories/')).data.results ?? []);
      setTcats((await api.get('/tickets/categories/')).data.results ?? []);
    } catch {
      setListError('Could not load categories.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const add = async (ev) => {
    ev.preventDefault();
    if (saving || !name.trim()) return;
    setSaving(true);
    setSaveError('');
    try {
      const url = which === 'ticket' ? '/tickets/categories/' : '/assets/categories/';
      await api.post(url, { name: name.trim() });
      setName('');
      await load();
    } catch (e) {
      setSaveError(e.response?.status === 403
        ? 'Forbidden: employees cannot add categories.'
        : (e.response?.data?.name?.join(' ') || 'Could not create category.'));
    } finally {
      setSaving(false);
    }
  };
  const catUrl = (kind, id = '') =>
    `${kind === 'ticket' ? '/tickets/categories/' : '/assets/categories/'}${id ? `${id}/` : ''}`;
  const doRename = async (ev) => {
    ev.preventDefault();
    if (!renaming || renameBusy || !renameValue.trim()) return;
    setRenameBusy(true);
    setRenameError('');
    try {
      await api.patch(catUrl(renaming.kind, renaming.cat.id), { name: renameValue.trim() });
      setRenaming(null);
      setMsg('Category renamed.');
      await load();
    } catch (e) {
      setRenameError(
        e.response?.data?.name?.join(' ') || parseApiError(e).global || 'Could not rename category.');
    } finally {
      setRenameBusy(false);
    }
  };
  const toggleActive = async (kind, cat) => {
    if (busy) return;
    if (!confirm(`${cat.is_active ? 'Deactivate' : 'Reactivate'} category "${cat.name}"?`)) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      await api.patch(catUrl(kind, cat.id), { is_active: !cat.is_active });
      setMsg(`Category "${cat.name}" ${cat.is_active ? 'deactivated' : 'reactivated'}.`);
      await load();
    } catch (e) {
      setErr(parseApiError(e).global || 'Could not update category.');
    } finally {
      setBusy(false);
    }
  };
  const doDelete = async () => {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await api.delete(catUrl(deleting.kind, deleting.cat.id));
      setDeleting(null);
      setMsg(`Category "${deleting.cat.name}" deleted.`);
      await load();
    } catch (e) {
      const refs = e?.response?.data;
      const count = typeof refs?.count === 'number' ? refs.count
        : (refs?.references ? Object.values(refs.references).reduce((a, b) => a + (Number(b) || 0), 0) : null);
      setErr(count
        ? `Cannot delete: still used by ${count} record(s). Deactivate instead.`
        : (parseApiError(e).global || 'Could not delete category.'));
      setDeleting(null);
    } finally {
      setDeleteBusy(false);
    }
  };
  const catColumns = [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Name' },
    { key: 'is_active', label: 'State', render: (c) => <Badge kind="status" value={c.is_active ? 'active' : 'inactive'} /> },
  ];
  const actionColumn = (kind) => ({
    key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (c) => isStaff ? (
      <div className="cell-actions">
        <button type="button" className="btn-small" onClick={() => { setRenameValue(c.name); setRenameError(''); setRenaming({ kind, cat: c }); }} disabled={busy}>Rename…</button>
        <button type="button" className="btn-small" onClick={() => toggleActive(kind, c)} disabled={busy}>
          {c.is_active ? 'Deactivate…' : 'Reactivate…'}
        </button>
        <button type="button" className="btn-small" onClick={() => setDeleting({ kind, cat: c })}>Delete…</button>
      </div>
    ) : '-',
  });
  return (
    <div>
      <PageHeader title="Categories" sub="Managed dropdown sources for ticket and asset forms." />
      {err && <div className="error-summary" role="alert">{err}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      {listError && <div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={load}>Retry</button></div>}
      <div className="panel">
        <div className="panel-title"><h4>Add category</h4></div>
        <div className="panel-pad">
        <form onSubmit={add}>
          <div className="row-gap">
            <select className="input input-auto" value={which} onChange={(e) => setWhich(e.target.value)} aria-label="Category type">
              <option value="ticket">Ticket category</option>
              <option value="asset">Asset category</option>
            </select>
            <input className="input grow" value={name} onChange={(e) => setName(e.target.value)} placeholder="New category name" aria-label="New category name" disabled={saving} />
            <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>
              {saving ? 'Adding…' : '+ Add'}
            </button>
          </div>
          {saveError && <div className="field-error" role="alert">{saveError}</div>}
        </form>
        </div>
      </div>
      <div className="panel">
        <div className="panel-title"><h4>Ticket categories</h4></div>
        {loading ? <div className="panel-pad"><LoadingRows n={3} /></div> : (
          <DataTable
            columns={[...catColumns, actionColumn('ticket')]}
            rows={tcats} keyOf={(c) => `t${c.id}`}
            emptyTitle="No ticket categories." emptyHint="Add one above."
          />
        )}
      </div>
      <div className="panel">
        <div className="panel-title"><h4>Asset categories</h4></div>
        {loading ? <div className="panel-pad"><LoadingRows n={3} /></div> : (
          <DataTable
            columns={[...catColumns, actionColumn('asset')]}
            rows={acats} keyOf={(c) => `a${c.id}`}
            emptyTitle="No asset categories." emptyHint="Add one above."
          />
        )}
      </div>
      {renaming && (
        <Modal title={`Rename ${renaming.kind} category`} onClose={() => { if (!renameBusy) setRenaming(null); }}>
          <form onSubmit={doRename}>
            <Field label="Name" required error={renameError && !renameValue.trim() ? 'Name is required.' : ''}>
              <input className="input" value={renameValue} onChange={(e) => setRenameValue(e.target.value)} disabled={renameBusy} autoFocus maxLength={100} />
            </Field>
            {renameError && renameValue.trim() ? <div className="field-error" role="alert">{renameError}</div> : null}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setRenaming(null)} disabled={renameBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={renameBusy || !renameValue.trim()}>
                {renameBusy ? 'Saving…' : 'Rename'}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete category "${deleting.cat.name}"?`}
          message="Deletion is blocked while tickets or assets still use this category — deactivate it instead in that case."
          confirmLabel="Delete category" danger busy={deleteBusy}
          onConfirm={doDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

export function RecycleBin() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const load = async () => {
    setLoading(true);
    setListError('');
    try { setItems((await api.get('/recycle-bin/')).data); }
    catch { setListError('Could not load deleted records. System Admin only.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const restore = async (e) => {
    const key = `${e.entity_type}:${e.object_id}`;
    setBusyId(key);
    try {
      const r = await api.post(`/recycle-bin/${e.entity_type}/${e.object_id}/restore/`, {}).catch((x) => x.response);
      alert(r.status === 200 ? 'Restored' : `Blocked: ${JSON.stringify(r.data.blockers ?? r.data)}`);
      await load();
    } finally {
      setBusyId(null);
    }
  };
  const hardDelete = async (e) => {
    const id = prompt(`PERMANENT delete ${e.entity_type}:${e.object_id}. Re-type the ID to confirm:`);
    if (id !== e.object_id) return;
    const reason = prompt('Reason (required, audited):');
    if (!reason) return;
    const r = await api.post(`/recycle-bin/${e.entity_type}/${e.object_id}/permanent/`,
      { confirm: id, reason }).catch((x) => x.response);
    alert(r.status === 200 ? 'Permanently deleted (audited).' : JSON.stringify(r.data));
    load();
  };
  return (
    <div>
      <PageHeader
        title="Recycle Bin"
        sub="Soft-deleted records. Restore or permanently delete (System Admin only)."
        actions={<button type="button" className="btn-ghost" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>}
      />
      {listError && <div className="error-summary" role="alert">{listError}</div>}
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={5} /></div> : (
          <>
            <DataTable
              columns={[
                { key: 'entity_type', label: 'Type' },
                { key: 'object_id', label: 'ID' },
                { key: 'repr', label: 'Record', render: (e) => <span className="ellipsis" title={e.repr ?? ''}>{e.repr}</span> },
                { key: 'deleted_by', label: 'Deleted by', render: (e) => e.deleted_by ?? '-' },
                {
                  key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (e) => {
                    const key = `${e.entity_type}:${e.object_id}`;
                    return (
                      <div className="cell-actions">
                        <button type="button" className="btn-small" onClick={() => restore(e)} disabled={busyId === key}>
                          {busyId === key ? 'Working…' : 'Restore'}
                        </button>
                        <button type="button" className="btn-small btn-danger" onClick={() => hardDelete(e)} disabled={busyId === key}>
                          Permanent delete…
                        </button>
                      </div>
                    );
                  },
                },
              ]}
              rows={items}
              keyOf={(e) => `${e.entity_type}:${e.object_id}`}
              emptyTitle="Recycle Bin is empty."
              emptyHint="Soft-deleted records will appear here."
            />
          </>
        )}
      </div>
    </div>
  );
}

export function VerifyEmail() {
  const [msg, setMsg] = useState('Verifying…');
  const run = async () => {
    const q = new URLSearchParams(location.hash.split('?')[1] || '');
    try {
      const r = await api.get(
        `/accounts/verify-email/confirm/?uid=${q.get('uid')}&token=${q.get('token')}`);
      setMsg(r.data.detail);
    } catch { setMsg('Invalid or expired link.'); }
  };
  useEffect(() => { run(); }, []);
  return (
    <div className="login-wrap">
      <div className="login-card">
        <h2>Email verification</h2>
        <p>{msg}</p>
        <p><a href="#/tickets">Back to tickets</a></p>
      </div>
    </div>
  );
}

export function ResetPassword() {
  const [pwd, setPwd] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setMsg('');
    const q = new URLSearchParams(location.hash.split('?')[1] || '');
    try {
      const r = await api.post('/accounts/password-reset/confirm/',
        { uid: q.get('uid'), token: q.get('token'), new_password: pwd });
      setMsg(r.data.detail);
    } catch { setMsg('Invalid or expired link (min 8 chars).'); }
    finally { setBusy(false); }
  };
  return (
    <div className="login-wrap">
      <div className="login-card">
        <h2>Set new password</h2>
        <form onSubmit={submit}>
          <div className="form-field">
            <label className="form-label" htmlFor="new-pwd">New password (8+ characters)</label>
            <input id="new-pwd" className="input" type="password" value={pwd} onChange={(e) => setPwd(e.target.value)} disabled={busy} />
          </div>
          <button type="submit" className="btn-primary" disabled={busy || pwd.length < 8}>
            {busy ? 'Updating…' : 'Update password'}
          </button>
        </form>
        {msg && <p>{msg}</p>}
      </div>
    </div>
  );
}

export function Profile() {
  const { user, refreshProfile } = useAuth();
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [pwCurrent, setPwCurrent] = useState('');
  const [pwNew, setPwNew] = useState('');
  const [pwConfirm, setPwConfirm] = useState('');
  const [pwBusy, setPwBusy] = useState(false);
  const [pwMsg, setPwMsg] = useState('');
  const [pwErr, setPwErr] = useState('');
  if (!user) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading profile…
      </p>
    );
  }
  const enabled = user.receive_ticket_emails !== false;
  const toggle = async () => {
    if (saving) return;
    setSaving(true);
    setMsg('');
    setErr('');
    try {
      await api.patch('/accounts/me/', { receive_ticket_emails: !enabled });
      await refreshProfile();
      setMsg(enabled ? 'Ticket-event emails turned off.' : 'Ticket-event emails turned on.');
    } catch {
      setErr('Could not save preference.');
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="form-wrap">
      <PageHeader title="My profile" sub="Account details and email preferences." />
      <div className="panel">
        <div className="panel-title"><h4>Account details</h4></div>
        <div className="panel-pad">
        <dl className="detail-grid">
          <dt>Employee ID</dt><dd>{user.employee_id}</dd>
          <dt>Email</dt><dd>{user.email}</dd>
          <dt>Role</dt><dd>{user.role.replace(/_/g, ' ')}</dd>
          <dt>Email verified</dt>
          <dd>{user.email_verified
            ? <Badge kind="status" value="resolved" label="Verified" />
            : <Badge kind="status" value="reopened" label="Unverified" />}</dd>
        </dl>
        </div>
      </div>
      <div className="panel">
        <div className="panel-title"><h4>Email preferences</h4></div>
        <div className="panel-pad">
        <label className="check-row">
          <input type="checkbox" checked={enabled} onChange={toggle} disabled={saving} />
          Receive ticket-event emails
        </label>
        <p className="muted small" style={{ marginTop: 'var(--sp-2)' }}>
          Applies to assignment and status-change emails only. In-app notifications,
          password resets, and email verification are always sent.
        </p>
        {saving && <p className="muted small"><span className="spinner" /> Saving…</p>}
        {msg && <div className="success-summary" role="status">{msg}</div>}
        {err && <div className="error-summary" role="alert">{err}</div>}
        </div>
      </div>
      <div className="panel">
        <div className="panel-title"><h4>Change password</h4></div>
        <div className="panel-pad">
        <form onSubmit={async (ev) => {
          ev.preventDefault();
          if (pwBusy) return;
          setPwMsg('');
          setPwErr('');
          if (pwNew !== pwConfirm) {
            setPwErr('New passwords do not match.');
            return;
          }
          setPwBusy(true);
          try {
            const r = await api.post('/accounts/change-password/', {
              current_password: pwCurrent, new_password: pwNew,
            });
            setPwCurrent('');
            setPwNew('');
            setPwConfirm('');
            setPwMsg(r.data.detail || 'Password updated.');
          } catch (e) {
            const p = parseApiError(e);
            setPwErr(p.global || p.fields.new_password || p.fields.current_password || 'Could not change password.');
          } finally {
            setPwBusy(false);
          }
        }} noValidate>
          <Field label="Current password" required>
            <input
              className="input" type="password" value={pwCurrent}
              onChange={(e) => setPwCurrent(e.target.value)}
              disabled={pwBusy} autoComplete="current-password"
            />
          </Field>
          <div className="form-grid">
            <Field label="New password" required hint="Validated against the configured password policy.">
              <input
                className="input" type="password" value={pwNew}
                onChange={(e) => setPwNew(e.target.value)}
                disabled={pwBusy} autoComplete="new-password"
              />
            </Field>
            <Field label="Confirm new password" required>
              <input
                className="input" type="password" value={pwConfirm}
                onChange={(e) => setPwConfirm(e.target.value)}
                disabled={pwBusy} autoComplete="new-password"
              />
            </Field>
          </div>
          {pwErr && <div className="error-summary" role="alert">{pwErr}</div>}
          {pwMsg && <div className="success-summary" role="status">{pwMsg}</div>}
          <div className="row-end">
            <button
              type="submit" className="btn-primary"
              disabled={pwBusy || !pwCurrent || !pwNew || !pwConfirm}
            >
              {pwBusy ? 'Updating…' : 'Change password'}
            </button>
          </div>
        </form>
        </div>
      </div>
    </div>
  );
}

function EmployeeEditModal({ user, onClose, onSaved }) {
  const [form, setForm] = useState({
    email: user?.email ?? '',
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    phone: user?.phone ?? '',
    job_title: user?.job_title ?? '',
    home_department: user?.home_department ?? '',
    is_active: user?.is_active ?? true,
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (ev) => {
    ev.preventDefault();
    if (saving) return;
    setFieldErrors({});
    setGlobalError('');
    const payload = {
      email: form.email.trim(),
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      phone: form.phone.trim(),
      job_title: form.job_title.trim(),
      is_active: form.is_active,
    };
    if (form.home_department !== '' && form.home_department != null) {
      payload.home_department = Number(form.home_department);
    } else {
      payload.home_department = null;
    }
    setSaving(true);
    try {
      await api.patch(`/accounts/users/${user.id}/`, payload);
      onSaved();
      onClose();
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title={`Edit employee ${user.employee_id}`} onClose={() => { if (!saving) onClose(); }}>
      <form onSubmit={submit} noValidate>
        {globalError && <div className="error-summary" role="alert">{globalError}</div>}
        <div className="form-grid">
          <Field label="Email" required error={fieldMsg(fieldErrors, 'email')}>
            <input className="input" type="email" value={form.email} onChange={(e) => set('email')(e.target.value)} disabled={saving} />
          </Field>
          <Field label="Department" error={fieldMsg(fieldErrors, 'home_department')}>
            <DepartmentSelect value={form.home_department} onChange={set('home_department')} disabled={saving} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="First name" error={fieldMsg(fieldErrors, 'first_name')}>
            <input className="input" value={form.first_name} onChange={(e) => set('first_name')(e.target.value)} disabled={saving} />
          </Field>
          <Field label="Last name" error={fieldMsg(fieldErrors, 'last_name')}>
            <input className="input" value={form.last_name} onChange={(e) => set('last_name')(e.target.value)} disabled={saving} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Phone" error={fieldMsg(fieldErrors, 'phone')}>
            <input className="input" value={form.phone} onChange={(e) => set('phone')(e.target.value)} disabled={saving} maxLength={30} />
          </Field>
          <Field label="Job title" error={fieldMsg(fieldErrors, 'job_title')}>
            <input className="input" value={form.job_title} onChange={(e) => set('job_title')(e.target.value)} disabled={saving} maxLength={100} />
          </Field>
        </div>
        <label className="check-row">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active')(e.target.checked)} disabled={saving} />
          Active
        </label>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Users() {
  const { isStaff, isAdmin, user: me } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [q, setQ] = useState('');
  const [sort, changeSort, orderingParam] = useSort();
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [rowBusy, setRowBusy] = useState(null);
  const [confirmUser, setConfirmUser] = useState(null); // {user, activate:boolean}
  const [roleTarget, setRoleTarget] = useState(null);
  const [roleForm, setRoleForm] = useState({ role: 'employee', can_create_tickets: true });
  const [roleBusy, setRoleBusy] = useState(false);
  const [roleError, setRoleError] = useState('');
  const [editingUser, setEditingUser] = useState(null);

  const USER_COLUMNS = [
    { key: 'employee_id', label: 'Employee ID', sortable: 'employee_id' },
    { key: 'email', label: 'Email', sortable: 'email', render: (u) => <span className="ellipsis" title={u.email}>{u.email}</span> },
    { key: 'role', label: 'Role', render: (u) => u.role.replace(/_/g, ' ') },
    { key: 'home_department', label: 'Department', render: (u) => u.home_department_name ?? '-' },
    { key: 'is_active', label: 'State', render: (u) => <Badge kind="status" value={u.is_active ? 'active' : 'inactive'} /> },
    {
      key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (u) => {
        const isSelf = me && u.id === me.id;
        return (
          <div className="cell-actions">
            {isStaff && (
              <button
                type="button" className="btn-small"
                onClick={() => setEditingUser(u)}
              >
                Edit…
              </button>
            )}
            {isStaff && (
              <button
                type="button" className="btn-small"
                disabled={rowBusy === u.id}
                onClick={() => setConfirmUser({ user: u, activate: !u.is_active })}
                title={isSelf ? 'This is your own account' : undefined}
              >
                {rowBusy === u.id ? 'Working…' : u.is_active ? 'Deactivate…' : 'Reactivate…'}
              </button>
            )}
            {isAdmin && (
              <button
                type="button" className="btn-small"
                onClick={() => openRoleModal(u)}
              >
                Role…
              </button>
            )}
            {!isStaff && !isAdmin ? '-' : null}
          </div>
        );
      },
    },
  ];
  const { visibleColumns: visibleUserColumns, toggleColumn: toggleUserColumn, resetColumns: resetUserColumns, tableVisible: userTableVisible, toggleTable: toggleUserTable } = useTableColumns(
    USER_COLUMNS.map((c) => c.key),
    ['employee_id', 'email', 'role', 'home_department', 'is_active', 'actions'],
  );
  const userColumns = USER_COLUMNS.filter((c) => visibleUserColumns.has(c.key));

  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setListError('Could not load employees.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadUrl('/accounts/users/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const search = (v) => {
    setQ(v);
    const p = new URLSearchParams();
    if (v) p.set('q', v);
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/accounts/users/${qs ? `?${qs}` : ''}`);
  };
  const refresh = () => {
    const p = new URLSearchParams();
    if (q) p.set('q', q);
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/accounts/users/${qs ? `?${qs}` : ''}`);
  };
  const changeUserSort = (field) => {
    const next = changeSort(field);
    const p = new URLSearchParams();
    if (q) p.set('q', q);
    const ord = orderingParam(next);
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/accounts/users/${qs ? `?${qs}` : ''}`);
  };
  const doActivate = async () => {
    if (!confirmUser || rowBusy) return;
    setRowBusy(confirmUser.user.id);
    try {
      await api.post(
        `/accounts/users/${confirmUser.user.id}/${confirmUser.activate ? 'reactivate' : 'deactivate'}/`, {});
      setMsg(`User "${confirmUser.user.employee_id}" ${confirmUser.activate ? 'reactivated' : 'deactivated'}.`);
      setConfirmUser(null);
      refresh();
    } catch (e) {
      setErr(parseApiError(e).global || 'Could not update user.');
      setConfirmUser(null);
    } finally {
      setRowBusy(null);
    }
  };
  const openRoleModal = (u) => {
    setRoleForm({ role: u.role, can_create_tickets: u.can_create_tickets !== false });
    setRoleError('');
    setRoleTarget(u);
  };
  const doChangeRole = async (ev) => {
    ev.preventDefault();
    if (!roleTarget || roleBusy) return;
    setRoleBusy(true);
    setRoleError('');
    try {
      await api.post(`/accounts/users/${roleTarget.id}/change_role/`, {
        role: roleForm.role, can_create_tickets: roleForm.can_create_tickets,
      });
      setMsg(`Role for "${roleTarget.employee_id}" updated.`);
      setRoleTarget(null);
      refresh();
    } catch (e) {
      const p = parseApiError(e);
      setRoleError(p.global || p.fields.role || 'Could not change role.');
    } finally {
      setRoleBusy(false);
    }
  };
  const run = async (kind) => {
    const ids = prompt('Comma-separated user IDs:');
    if (!ids) return;
    const list = ids.split(',').map((s) => Number(s.trim())).filter(Boolean);
    if (!list.length) return;
    const url = kind === 'activate' ? '/accounts/users/bulk_activate/' : '/accounts/users/bulk_delete/';
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const prev = await api.post(url, { ids: list, preview: true, ...(kind === 'activate' ? { activate: true } : {}) });
      if (!confirm(`Affects ${prev.data.affected ?? prev.data.preview?.length}. Confirm?`)) return;
      const res = await api.post(url, { ids: list, preview: false, confirm: true, ...(kind === 'activate' ? { activate: true } : { reason: 'bulk' }) });
      const d = res.data;
      setMsg(`Done: ${d.successful?.length ?? 0} successful`
        + (d.skipped ? `, ${d.skipped.length} skipped` : '')
        + (d.failed?.length ? `, ${d.failed.length} failed` : ''));
      refresh();
    } catch (e) {
      setErr(e.response?.status === 403
        ? 'Forbidden: this bulk operation requires elevated permissions.'
        : 'Bulk operation failed.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <PageHeader
        title="Employees"
        sub={count != null ? `${count} accounts` : 'Directory, creation, and bulk import.'}
        actions={<>
          {isStaff && <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>+ Add employee</button>}
          {isStaff && <button type="button" className="btn-secondary" onClick={() => setShowImport(true)}>Bulk import…</button>}
          {isStaff && <button type="button" className="btn-ghost" onClick={() => run('activate')} disabled={busy}>Bulk activate…</button>}
          {isStaff && <button type="button" className="btn-ghost" onClick={() => run('delete')} disabled={busy}>Bulk soft-delete…</button>}
        </>}
      />
      {err && <div className="error-summary" role="alert">{err}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      <div className="filter-bar" role="search">
        <input
          className="input grow" value={q} onChange={(e) => search(e.target.value)}
          placeholder="Search employee ID or email…" aria-label="Search employees"
        />
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={refresh}>Retry</button></div></div>
          : (<>
            <TableControls tableVisible={userTableVisible} onToggleTable={toggleUserTable} columns={USER_COLUMNS} visible={visibleUserColumns} onToggleColumn={toggleUserColumn} onReset={resetUserColumns} />
            {userTableVisible ? (
              <DataTable
                columns={userColumns}
                rows={items}
                keyOf={(u) => u.id}
                sort={sort}
                onSort={changeUserSort}
                emptyTitle="No employees found."
                emptyHint="Adjust the search or add a new employee."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
      <p className="muted small">Import template key: employee_id — roles never change via bulk import.</p>
      {showCreate && <EmployeeCreateModal onClose={() => setShowCreate(false)} onCreated={refresh} />}
      {showImport && <EmployeeImportModal onClose={() => setShowImport(false)} onImported={refresh} />}
      {editingUser && (
        <EmployeeEditModal
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={() => { setMsg('Employee updated.'); setEditingUser(null); refresh(); }}
        />
      )}
      {confirmUser && (
        <ConfirmDialog
          title={`${confirmUser.activate ? 'Reactivate' : 'Deactivate'} "${confirmUser.user.employee_id}"?`}
          message={confirmUser.activate
            ? 'This restores login access for the account.'
            : 'This blocks login for the account. Their records and history are kept.'
            + (me && confirmUser.user.id === me.id ? ' WARNING: this is your own account — you will lock yourself out.' : '')}
          confirmLabel={confirmUser.activate ? 'Reactivate' : 'Deactivate'}
          danger={!confirmUser.activate}
          busy={rowBusy === confirmUser.user.id}
          onConfirm={doActivate}
          onCancel={() => setConfirmUser(null)}
        />
      )}
      {roleTarget && (
        <Modal title={`Change role — ${roleTarget.employee_id}`} onClose={() => { if (!roleBusy) setRoleTarget(null); }}>
          <form onSubmit={doChangeRole}>
            <Field label="Role">
              <select
                className="input" value={roleForm.role}
                onChange={(e) => setRoleForm((f) => ({ ...f, role: e.target.value }))}
                disabled={roleBusy}
              >
                <option value="employee">Employee</option>
                <option value="it_support">IT Support</option>
                <option value="it_manager">IT Manager</option>
                <option value="system_admin">System Admin</option>
              </select>
            </Field>
            <label className="check-row">
              <input
                type="checkbox" checked={roleForm.can_create_tickets}
                onChange={(e) => setRoleForm((f) => ({ ...f, can_create_tickets: e.target.checked }))}
                disabled={roleBusy}
              />
              Can create tickets
            </label>
            {roleError && <div className="field-error" role="alert">{roleError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setRoleTarget(null)} disabled={roleBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={roleBusy}>
                {roleBusy ? 'Saving…' : 'Change role'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function DepartmentModal({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: initial?.name ?? '', code: initial?.code ?? '',
    description: initial?.description ?? '', head: initial?.head ?? '',
    is_active: initial?.is_active ?? true,
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (ev) => {
    ev.preventDefault();
    if (saving) return;
    setFieldErrors({});
    setGlobalError('');
    const payload = {
      name: form.name.trim(), code: form.code.trim(),
      description: form.description.trim(), is_active: form.is_active,
    };
    if (form.head !== '' && form.head != null) payload.head = Number(form.head);
    setSaving(true);
    try {
      if (initial) await api.patch(`/accounts/departments/${initial.id}/`, payload);
      else await api.post('/accounts/departments/', payload);
      onSaved();
      onClose();
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title={initial ? `Rename ${initial.name}` : 'New department'} onClose={() => { if (!saving) onClose(); }}>
      <form onSubmit={submit} noValidate>
        {globalError && <div className="error-summary" role="alert">{globalError}</div>}
        <div className="form-grid">
          <Field label="Name" required error={fieldMsg(fieldErrors, 'name')}>
            <input className="input" value={form.name} onChange={(e) => set('name')(e.target.value)} disabled={saving} maxLength={100} />
          </Field>
          <Field label="Code" required error={fieldMsg(fieldErrors, 'code')} hint="Short unique code, e.g. ENG.">
            <input className="input" value={form.code} onChange={(e) => set('code')(e.target.value)} disabled={saving} maxLength={20} />
          </Field>
        </div>
        <Field label="Description" error={fieldMsg(fieldErrors, 'description')}>
          <textarea className="input" rows={2} value={form.description} onChange={(e) => set('description')(e.target.value)} disabled={saving} />
        </Field>
        <Field label="Head (optional)" error={fieldMsg(fieldErrors, 'head')}>
          <UserSelect value={form.head} onChange={set('head')} disabled={saving} label="Department head" />
        </Field>
        <label className="check-row">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active')(e.target.checked)} disabled={saving} />
          Active
        </label>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : initial ? 'Save changes' : 'Create department'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Departments() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const DEPARTMENT_COLUMNS = [
    { key: 'name', label: 'Name' },
    { key: 'code', label: 'Code' },
    { key: 'head', label: 'Head', render: (d) => d.head_email ?? '-' },
    { key: 'members', label: 'Members', render: (d) => d.member_count ?? '-' },
    { key: 'is_active', label: 'State', render: (d) => <Badge kind="status" value={d.is_active ? 'active' : 'inactive'} /> },
  ];
  const { visibleColumns: visibleDepartmentColumns, toggleColumn: toggleDepartmentColumn, resetColumns: resetDepartmentColumns, tableVisible: departmentTableVisible, toggleTable: toggleDepartmentTable } = useTableColumns(
    DEPARTMENT_COLUMNS.map((c) => c.key),
    ['name', 'code', 'head', 'members', 'is_active'],
  );
  const departmentColumns = DEPARTMENT_COLUMNS.filter((c) => visibleDepartmentColumns.has(c.key));

  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setListError('Could not load departments.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadUrl('/accounts/departments/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = () => loadUrl('/accounts/departments/');

  const toggleActive = async (d) => {
    if (busy) return;
    if (!confirm(`${d.is_active ? 'Deactivate' : 'Reactivate'} department "${d.name}"?`)) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      await api.patch(`/accounts/departments/${d.id}/`, { is_active: !d.is_active });
      setMsg(`Department "${d.name}" ${d.is_active ? 'deactivated' : 'reactivated'}.`);
      refresh();
    } catch (e) {
      setErr(parseApiError(e).global || 'Could not update department.');
    } finally {
      setBusy(false);
    }
  };
  const doDelete = async () => {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await api.delete(`/accounts/departments/${deleting.id}/`);
      setDeleting(null);
      setMsg(`Department "${deleting.name}" deleted.`);
      refresh();
    } catch (e) {
      const p = parseApiError(e);
      const refs = e?.response?.data?.references;
      setErr(refs
        ? `Cannot delete: still referenced (${Object.entries(refs).map(([k, v]) => `${k}: ${v}`).join(', ')}). Deactivate instead.`
        : (p.global || 'Could not delete department.'));
      setDeleting(null);
    } finally {
      setDeleteBusy(false);
    }
  };
  return (
    <div>
      <PageHeader
        title="Departments"
        sub={count != null ? `${count} departments` : 'Home departments, ticket routing, and membership.'}
        actions={<>
          {isStaff && <button type="button" className="btn-primary" onClick={() => setCreating(true)}>+ New department</button>}
        </>}
      />
      {err && <div className="error-summary" role="alert">{err}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={5} /></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={refresh}>Retry</button></div></div>
          : (<>
            <TableControls tableVisible={departmentTableVisible} onToggleTable={toggleDepartmentTable} columns={DEPARTMENT_COLUMNS} visible={visibleDepartmentColumns} onToggleColumn={toggleDepartmentColumn} onReset={resetDepartmentColumns} />
            {departmentTableVisible ? (
              <DataTable
                columns={[...departmentColumns, {
                  key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (d) => isStaff ? (
                    <div className="cell-actions">
                      <button type="button" className="btn-small" onClick={() => setEditing(d)} disabled={busy}>Rename…</button>
                      <button type="button" className="btn-small" onClick={() => toggleActive(d)} disabled={busy}>
                        {d.is_active ? 'Deactivate…' : 'Reactivate…'}
                      </button>
                      <button type="button" className="btn-small btn-danger" onClick={() => setDeleting(d)}>Delete…</button>
                    </div>
                  ) : '-',
                }]}
                rows={items}
                keyOf={(d) => d.id}
                emptyTitle="No departments."
                emptyHint="IT staff can add the first one."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
      {creating && <DepartmentModal onClose={() => setCreating(false)} onSaved={() => { setMsg('Department created.'); refresh(); }} />}
      {editing && <DepartmentModal initial={editing} onClose={() => setEditing(null)} onSaved={() => { setMsg('Department updated.'); refresh(); }} />}
      {deleting && (
        <ConfirmDialog
          title={`Delete department "${deleting.name}"?`}
          message="This soft-deletes the department. If members or tickets still reference it, deletion is blocked — deactivate instead."
          confirmLabel="Delete department" danger busy={deleteBusy}
          onConfirm={doDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
