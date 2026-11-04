import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, DataTable, EmptyState,
  Field, LoadingRows, Modal, PageHeader, Pager, TableControls,
  useTableColumns,
} from './components';
import { fieldMsg, parseApiError, fetchPage } from './api-utils';

const UNIT_CHOICES = ['pcs', 'box', 'set', 'unit', 'meter', 'other'];
const UNIT_LABELS = { pcs: 'Pieces', box: 'Box', set: 'Set', unit: 'Unit', meter: 'Meter', other: 'Other' };
const FULFILLABLE_STATUSES = ['submitted', 'pending_approval', 'approved', 'in_progress', 'pending_employee'];

const fmtMoney = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(v);
};

const fmtDate = (d) => d ? new Date(`${d}T00:00:00`).toLocaleDateString() : '—';
const fmtDateTime = (d) => d ? new Date(d).toLocaleString() : '—';

function stockStatus(item) {
  const avail = item.available != null ? item.available : (Number(item.quantity) - Number(item.reserved || 0));
  if (avail <= 0) return 'out_of_stock';
  if (item.reorder_threshold != null && avail <= Number(item.reorder_threshold)) return 'low_stock';
  return 'in_stock';
}

function stockStatusBadge(item) {
  const s = stockStatus(item);
  return <Badge kind="status" value={s} />;
}

/** Read ?q=&category=&low_stock= from a hash like #/inventory/items?q=x */
function hashQueryParams(hash = location.hash) {
  try { return new URLSearchParams(String(hash).split('?')[1] || ''); } catch { return new URLSearchParams(); }
}

function initialFilters() {
  const p = hashQueryParams();
  return {
    q: p.get('q') ?? '',
    category: p.get('category') ?? '',
    low_stock: p.get('low_stock') ?? '',
  };
}

/**
 * Inventory dashboard: operational summaries from the backend dashboard
 * endpoint plus recent purchase receipts and pending service-request
 * fulfilments. Cards navigate to the relevant filtered views.
 */
export function Inventory() {
  const { isStaff } = useAuth();
  const [dashboard, setDashboard] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [d, r, s] = await Promise.all([
        api.get('/inventory/stock-items/dashboard/'),
        api.get('/inventory/purchase-receipts/'),
        api.get('/services/requests/'),
      ]);
      setDashboard(d.data);
      const rdata = r.data.results ?? r.data ?? [];
      setReceipts(Array.isArray(rdata) ? rdata.slice(0, 5) : []);
      const sdata = s.data.results ?? s.data ?? [];
      const pend = Array.isArray(sdata) ? sdata.filter((sr) => FULFILLABLE_STATUSES.includes(sr.status)) : [];
      setPending(pend.slice(0, 5));
    } catch (e) {
      const p = parseApiError(e);
      setError(p.global || 'Failed to load the inventory dashboard.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const totalItems = dashboard?.total_items ?? 0;
  const totalUnits = Number(dashboard?.total_units ?? 0);
  const reserved = Number(dashboard?.reserved ?? 0);
  const available = totalUnits - reserved;
  const lowStock = dashboard?.low_stock ?? 0;
  const outOfStock = dashboard?.out_of_stock ?? 0;

  if (loading) return <div className="p-3" role="status"><span className="spinner" aria-hidden="true" /> Loading inventory dashboard…</div>;
  if (error) return <div className="p-3"><div className="alert alert-danger" role="alert">{error}</div></div>;

  const card = (title, value, tone, hint, to) => (
    <div className="col-md-4" key={title}>
      <div className="card p-3">
        <div className="row-gap" style={{ alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div>
            <div className="text-muted small">{title}</div>
            <div className="row-gap" style={{ alignItems: 'baseline', gap: 'var(--sp-1)' }}>
              <span className={`h3 mb-0 ${tone ? 'text-' + tone : ''}`}>{value}</span>
              {hint ? <span className="text-muted small">· {hint}</span> : null}
            </div>
          </div>
          {to ? (
            <a className="btn-small btn-primary" href={to} aria-label={`Go to ${title}`}>View</a>
          ) : null}
        </div>
      </div>
    </div>
  );

  return (
    <div className="container-fluid p-3">
      <PageHeader title="Inventory" sub="Stock items, receiving, reservations and transaction history." actions={<>
        {isStaff && <a className="btn-primary" href="#/inventory/items/new">+ New stock item</a>}
        {isStaff && <a className="btn-secondary" href="#/inventory/receive">+ Receive stock</a>}
        <a className="btn-secondary" href="#/inventory/items">Browse stock items</a>
      </>} />
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="row g-3 mb-3">
        {card('Total items', totalItems, 'blue', 'Stock records', '#/inventory/items')}
        {card('On-hand units', totalUnits, '', 'Total quantity across items', '#/inventory/items')}
        {card('Available', available, 'green', 'On-hand minus reserved', '#/inventory/items')}
        {card('Reserved', reserved, 'amber', 'Allocated to reservations', '#/inventory/reservations')}
        {card('Low stock', lowStock, 'amber', 'At or below reorder threshold', '#/inventory/items?low_stock=1')}
        {card('Out of stock', outOfStock, 'red', 'No units on hand', '#/inventory/items')}
      </div>
      <div className="panel mb-3">
        <div className="panel-title"><h4>Recent stock movements</h4></div>
        <div className="panel-pad">
          {dashboard?.recent_movements && dashboard.recent_movements.length ? (
            <table className="table table-sm">
              <thead><tr><th>Item</th><th>Type</th><th>Qty</th><th>Reference</th><th>Recorded</th></tr></thead>
              <tbody>
                {dashboard.recent_movements.slice(0, 8).map((m) => (
                  <tr key={m.id}>
                    <td>{m.stock_item_name}</td>
                    <td><Badge kind="status" value={m.movement_type} /></td>
                    <td>{m.quantity}</td>
                    <td>{m.reference || '—'}</td>
                    <td>{fmtDateTime(m.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No stock movements yet." hint="Movements appear here when stock is received, issued, reserved or adjusted." />
          )}
        </div>
      </div>
      <div className="row g-3">
        <div className="col-md-6">
          <div className="panel mb-3">
            <div className="panel-title">
              <h4>Recent purchase receipts</h4>
              <div className="panel-actions">
                {isStaff && <a className="btn-small btn-secondary" href="#/inventory/receive">New receipt…</a>}
              </div>
            </div>
            <div className="panel-pad">
              {receipts.length ? (
                <table className="table table-sm">
                  <thead><tr><th>Reference</th><th>Vendor</th><th>Date</th><th>Total cost</th><th>Lines</th></tr></thead>
                  <tbody>
                    {receipts.map((r) => (
                      <tr key={r.id}>
                        <td>{r.purchase_reference || `#${r.id}`}</td>
                        <td>{r.vendor_name || `Vendor #${r.vendor}`}</td>
                        <td>{fmtDate(r.purchase_date)}</td>
                        <td>{fmtMoney(r.total_cost)}</td>
                        <td className="cell-muted">{(r.lines?.length ?? 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState title="No purchase receipts yet." hint="Received purchase orders appear here." />
              )}
            </div>
          </div>
        </div>
        <div className="col-md-6">
          <div className="panel mb-3">
            <div className="panel-title"><h4>Pending fulfilment requests</h4></div>
            <div className="panel-pad">
              {pending.length ? (
                <table className="table table-sm">
                  <thead><tr><th>Number</th><th>Service</th><th>Requester</th><th>Status</th><th>Submitted</th></tr></thead>
                  <tbody>
                    {pending.map((sr) => (
                      <tr key={sr.id}>
                        <td><a className="row-title" href={`#/service-requests/${sr.id}`}>{sr.request_number}</a></td>
                        <td>{sr.catalogue_item_name || '—'}</td>
                        <td>{sr.requester_name || `User #${sr.requester}`}</td>
                        <td><Badge kind="status" value={sr.status} /></td>
                        <td>{fmtDateTime(sr.submitted_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState title="No pending fulfilment requests." hint="Service requests awaiting stock fulfilment appear here." />
              )}
              <div className="row-end">
                <a className="btn-small btn-secondary" href="#/inventory/fulfil">Fulfil a request…</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Stock item listing: search, category and low-stock filters, pagination,
 * stock-status badges and navigation to item details.
 */
export function InventoryItems() {
  const { isStaff, isAdmin } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [f, setF] = useState(initialFilters());
  const [sel, setSel] = useState(new Set());

  const [categories, setCategories] = useState([]);

  const buildUrl = useCallback((over) => {
    const merged = { ...f, ...over };
    const p = new URLSearchParams();
    if (merged.q) p.set('q', merged.q);
    if (merged.category) p.set('category', merged.category);
    if (merged.low_stock) p.set('low_stock', '1');
    const qs = p.toString();
    return `/inventory/stock-items/${qs ? `?${qs}` : ''}`;
  }, [f]);

  const loadUrl = useCallback(async (url) => {
    setLoading(true); setListError('');
    try {
      const pg = await fetchPage(url);
      const rows = pg.items;
      setItems(rows);
      setCount(pg.count); setNext(pg.next); setPrevious(pg.previous);
      const cats = [...new Set(rows.map((i) => i.category).filter(Boolean))].sort();
      setCategories((prev) => {
        const merged = [...new Set([...prev, ...cats])].sort();
        return merged;
      });
    } catch {
      setListError('Could not load stock items.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (cancelled) return;
      setSel(new Set());
      await loadUrl(buildUrl());
    })();
    return () => { cancelled = true; };
  }, [buildUrl, loadUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyFilters = useCallback((patch) => {
    setF((prev) => ({ ...prev, ...patch }));
    setSel(new Set());
    loadUrl(buildUrl(patch));
  }, [buildUrl, loadUrl]);

  const clearFilters = useCallback(() => {
    setF({ q: '', category: '', low_stock: '' });
    setSel(new Set());
    loadUrl(buildUrl());
  }, [buildUrl, loadUrl]);

  const toggle = (id) => setSel((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const ITEM_COLUMNS = [
    { key: 'sku', label: 'SKU', sortable: false, render: (i) => <a className="row-title" href={`#/inventory/items/${i.id}`}>{i.sku}</a> },
    { key: 'name', label: 'Name', sortable: false, render: (i) => <span className="ellipsis" title={i.name ?? ''}>{i.name || <span className="cell-muted">—</span>}</span> },
    { key: 'category', label: 'Category', sortable: false, render: (i) => i.category ? <span className="ellipsis" title={i.category}>{i.category}</span> : <span className="cell-muted">—</span> },
    { key: 'unit', label: 'Unit', sortable: false, render: (i) => UNIT_LABELS[i.unit] ?? i.unit },
    { key: 'quantity', label: 'Qty', sortable: false, render: (i) => String(i.quantity ?? 0) },
    { key: 'available', label: 'Available', sortable: false, render: (i) => String(i.available != null ? i.available : Number(i.quantity) - Number(i.reserved || 0)) },
    { key: 'reserved', label: 'Reserved', sortable: false, render: (i) => String(i.reserved ?? 0) },
    { key: 'threshold', label: 'Reorder', sortable: false, render: (i) => String(i.reorder_threshold ?? 0) },
    { key: 'unit_cost', label: 'Unit cost', sortable: false, render: (i) => i.unit_cost != null ? <span className="cell-wrap">{fmtMoney(i.unit_cost)}</span> : <span className="cell-muted">—</span> },
    { key: 'status', label: 'Status', sortable: false, render: stockStatusBadge },
    ...(isStaff ? [{ key: 'actions', label: 'Actions', thClass: 'table-actions', render: (i) => (
      <div className="cell-actions">
        <button type="button" className="btn-small" onClick={() => { window.location.hash = `#/inventory/receive?item=${i.id}`; }} title={`Receive stock for ${i.name}`}>Receive</button>
        <a className="btn-small" href={`#/inventory/items/${i.id}`} title={`View ${i.name}`}>View</a>
      </div>
    )}] : []),
  ];

  const { visibleColumns, toggleColumn, resetColumns, tableVisible, toggleTable } = useTableColumns(
    'inventory-items',
    ITEM_COLUMNS.map((c) => c.key),
    isStaff ? ['sku', 'name', 'category', 'quantity', 'available', 'status', 'actions']
      : ['sku', 'name', 'category', 'quantity', 'available', 'status'],
  );
  const columns = ITEM_COLUMNS.filter((c) => visibleColumns.has(c.key));
  const filtersActive = !!(f.q || f.category || f.low_stock);

  const filters = [
    <div key="search" className="field-inline grow">
      <div className="caption">Search</div>
      <input className="input" value={f.q} onChange={(e) => applyFilters({ q: e.target.value })} placeholder="Name or SKU…" aria-label="Search stock items" />
    </div>,
    <div key="category" className="field-inline">
      <div className="caption">Category</div>
      <select className="input" value={f.category} onChange={(e) => applyFilters({ category: e.target.value })} aria-label="Filter by category">
        <option value="">All categories</option>
        {categories.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </div>,
    <div key="low_stock" className="field-inline">
      <div className="caption">Stock</div>
      <select className="input" value={f.low_stock} onChange={(e) => applyFilters({ low_stock: e.target.value })} aria-label="Filter by low stock">
        <option value="">All stock</option>
        <option value="1">Low stock (qty ≤ reorder threshold)</option>
      </select>
    </div>,
  ];

  return (
    <div>
      <PageHeader title="Stock items" sub={count != null ? `${count} stock item${count === 1 ? '' : 's'} in scope` : undefined} actions={<>
        {isStaff && <a className="btn-primary" href="#/inventory/items/new">+ New stock item</a>}
      </>} />
      {listError && <div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl(buildUrl())}>Retry</button></div>}
      <div className="filter-bar" role="search">{filters}
        {filtersActive && (
          <button type="button" className="btn-ghost" onClick={clearFilters} aria-label="Clear all inventory filters">Clear filters</button>
        )}
      </div>
      {isStaff && sel.size > 0 && (
        <div className="toolbar" role="toolbar" aria-label="Bulk actions">
          <span className="muted small">{sel.size} selected</span>
          <button type="button" className="btn-small" onClick={() => { setSel(new Set()); }} >Clear</button>
        </div>
      )}
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : items.length === 0 ? (
            <div className="panel-pad">
              <EmptyState
                title={filtersActive ? 'No stock items match the current filters.' : 'No stock items yet.'}
                hint={filtersActive ? 'Adjust the search text or clear the filters to widen the results.'
                  : (isStaff ? 'Add the first stock item, or receive stock against an item.' : 'No stock items are available.')}
                action={isStaff ? <a className="btn-primary" href="#/inventory/items/new">+ New stock item</a> : null}
              />
            </div>
          ) : (
            <>
              <TableControls tableVisible={tableVisible} onToggleTable={toggleTable} columns={ITEM_COLUMNS} visible={visibleColumns} onToggleColumn={toggleColumn} onReset={resetColumns} />
              {tableVisible ? (
                <DataTable
                  columns={columns} rows={items} keyOf={(i) => String(i.id)}
                  selected={isStaff ? sel : undefined} onToggle={isStaff ? toggle : undefined}
                  emptyTitle="No stock items." emptyHint="Adjust filters or add a new stock item."
                />
              ) : <p className="muted">Table hidden.</p>}
              <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading}
                onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
            </>
          )}
      </div>
      {isAdmin && sel.size > 0 && (
        <ConfirmDialog
          title="Delete selected stock items?"
          message={`Soft-delete ${sel.size} selected stock item(s)? They will no longer appear in stock lists.`}
          confirmLabel="Delete" danger busy={false}
          onConfirm={() => {
            const ids = [...sel];
            Promise.all(ids.map((id) => api.delete(`/inventory/stock-items/${id}/`).catch(() => {}))).then(() => {
              setSel(new Set());
              loadUrl(buildUrl());
            });
          }}
          onCancel={() => setSel(new Set())}
        />
      )}
    </div>
  );
}

/**
 * Stock item detail: on-hand vs reserved stock, movement history and
 * staff stock actions (receive / issue / return / damage / adjust).
 */
export function StockItemDetail({ id }) {
  const { isStaff, isAdmin } = useAuth();
  const [item, setItem] = useState(null);
  const [movements, setMovements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [openAction, setOpenAction] = useState(null); // {type, item}
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setLoadError('');
    try {
      const [it, mv] = await Promise.all([
        api.get(`/inventory/stock-items/${id}/`),
        api.get(`/inventory/stock-items/movements/?stock_item=${id}`),
      ]);
      setItem(it.data);
      setMovements(Array.isArray(mv.data) ? mv.data : (mv.data.results ?? []));
    } catch (e) {
      setLoadError(parseApiError(e).global || 'Could not load the stock item.');
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const runAction = useCallback(async (type, payload) => {
    if (busy) return;
    setBusy(true); setActionError(''); setOkMsg('');
    try {
      await api.post(`/inventory/stock-items/${id}/${type}/`, payload);
      setOkMsg(`${type} recorded.`);
      setOpenAction(null);
      await load();
    } catch (e) {
      const p = parseApiError(e);
      setActionError(p.global || `Stock ${type} failed.`);
    } finally {
      setBusy(false);
    }
  }, [id, busy, load]);

  const availableQty = item ? (item.available != null ? item.available : Number(item.quantity) - Number(item.reserved || 0)) : 0;

  if (loading) return <div className="p-3" role="status"><span className="spinner" aria-hidden="true" /> Loading…</div>;
  if (loadError) return <div className="p-3"><div className="alert alert-danger" role="alert">{loadError}</div></div>;

  return (
    <div>
      <PageHeader title={item.name} sub={`${item.sku} · ${item.category || 'No category'}`} actions={<>
        <a className="btn-secondary" href="#/inventory/items">&larr; Back to stock items</a>
        {isStaff && <a className="btn-primary" href={`#/inventory/items/${id}/edit`}>Edit item</a>}
        {isAdmin && <button type="button" className="btn-danger" onClick={() => doDeleteItem()}>Delete item</button>}
        {isStaff && <button type="button" className="btn-secondary" onClick={() => setOpenAction({ type: 'receive', item })}>Receive stock</button>}
      </>} />
      {okMsg && <div className="success-summary" role="status">{okMsg}</div>}
      {actionError && <div className="error-summary" role="alert">{actionError}</div>}
      <div className="row g-3 mb-3">
        <div className="col-md-3"><div className="card p-3"><div className="text-muted small">On-hand quantity</div><h4>{item.quantity}</h4></div></div>
        <div className="col-md-3"><div className="card p-3"><div className="text-muted small">Available</div><h4>{availableQty}</h4></div></div>
        <div className="col-md-3"><div className="card p-3"><div className="text-muted small">Reserved</div><h4>{item.reserved}</h4></div></div>
        <div className="col-md-3"><div className="card p-3"><div className="text-muted small">Reorder threshold</div><h4>{item.reorder_threshold}</h4></div></div>
      </div>
      <div className="row g-3 mb-3">
        <div className="col-md-6">
          <div className="card p-3 mb-3">
            <div className="row-gap" style={{ alignItems: 'center' }}>
              <div><div className="text-muted small">Stock status</div></div>
              <div className="spacer" />
              {stockStatusBadge(item)}
            </div>
          </div>
          <div className="card p-3">
            <div className="text-muted small">Unit</div>
            <div>{UNIT_LABELS[item.unit] ?? item.unit}</div>
            <div className="text-muted small">Preferred vendor</div>
            <div>{item.preferred_vendor_name || '—'}</div>
            <div className="text-muted small">Unit cost</div>
            <div>{item.unit_cost != null ? fmtMoney(item.unit_cost) : '—'}</div>
            <div className="text-muted small">Description</div>
            <div>{item.description || '—'}</div>
            <div className="text-muted small">SKU</div>
            <div>{item.sku}</div>
          </div>
        </div>
        <div className="col-md-6">
          <div className="card p-3">
            <div className="panel-title"><h4>Movement history</h4></div>
            <div className="panel-pad">
              {movements.length ? (
                <table className="table table-sm">
                  <thead><tr><th>Type</th><th>Qty</th><th>Balance after</th><th>Reference</th><th>Recorded by</th><th>When</th></tr></thead>
                  <tbody>
                    {movements.slice(0, 30).map((m) => (
                      <tr key={m.id}>
                        <td><Badge kind="status" value={m.movement_type} /></td>
                        <td>{m.quantity}</td>
                        <td>{m.new_balance}</td>
                        <td>{m.reference || '—'}</td>
                        <td>{m.recorded_by_name || `User #${m.recorded_by}`}</td>
                        <td>{fmtDateTime(m.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <EmptyState title="No movements." hint="Stock movements for this item appear here." />}
            </div>
          </div>
        </div>
      </div>
      {openAction && (
        <StockActionModal
          item={item} action={openAction.type} busy={busy}
          onClose={() => { if (!busy) setOpenAction(null); }}
          onSuccess={runAction}
        />
      )}
      {isAdmin && (
        <ConfirmDialog
          title={`Delete stock item "${item.name}"?`}
          message="This soft-deletes the item. It will no longer appear in stock lists; movements are kept for audit."
          confirmLabel="Delete item" danger busy={false}
          onConfirm={doDeleteItem}
          onCancel={() => {}}
        />
      )}
    </div>
  );

  function doDeleteItem() {
    if (!confirm(`Soft-delete "${item.name}"?`)) return;
    api.delete(`/inventory/stock-items/${id}/`).then(() => {
      window.location.hash = '#/inventory/items';
    }).catch((e) => {
      const p = parseApiError(e);
      setActionError(p.global || 'Could not delete the stock item.');
    });
  }
}

/** Stock receive / issue / return / damage / adjust action modal. */
function StockActionModal({ action, busy, onClose, onSuccess }) {
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [reference, setReference] = useState('');
  const [employee, setEmployee] = useState('');
  const [department, setDepartment] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [users, setUsers] = useState([]);
  const [depts, setDepts] = useState([]);
  const [loadingRefs, setLoadingRefs] = useState(false);

  useEffect(() => {
    if (action !== 'issue') return;
    setLoadingRefs(true);
    Promise.all([
      api.get('/accounts/users/').then((r) => setUsers(r.data.results ?? r.data ?? [])).catch(() => setUsers([])),
      api.get('/accounts/departments/').then((r) => setDepts(r.data.results ?? r.data ?? [])).catch(() => setDepts([])),
    ]).finally(() => setLoadingRefs(false));
  }, [action]);

  const labels = {
    receive: 'Receive stock', issue: 'Issue stock', return: 'Return stock',
    damage: 'Record damage', adjust: 'Adjust stock',
  };
  const submit = async (ev) => {
    ev.preventDefault();
    setFieldErrors({}); setGlobalError('');
    const q = Number(qty);
    if (!q || q <= 0 && action !== 'adjust') { setGlobalError('Enter a valid quantity.'); return; }
    if (action === 'adjust' && !reason) { setGlobalError('Reason is required for adjustments.'); return; }
    const payload = { quantity: q, reason: reason.trim(), reference: reference.trim() };
    if (action === 'issue') { payload.employee = Number(employee) || null; payload.department = Number(department) || null; }
    try {
      await onSuccess(action, payload);
    } catch (e) {
      const p = parseApiError(e);
      setGlobalError(p.global || 'The stock action could not be completed.');
      if (p.fields.quantity) setFieldErrors((prev) => ({ ...prev, quantity: p.fields.quantity }));
      if (p.fields.reason) setFieldErrors((prev) => ({ ...prev, reason: p.fields.reason }));
    }
  };

  return (
    <Modal title={labels[action]} onClose={onClose} size="md">
      <form onSubmit={submit} noValidate>
        <Field label="Quantity" required hint="Positive number (adjustment may be negative to reduce stock).">
          <input className="input" type="number" value={qty} onChange={(e) => setQty(e.target.value)} disabled={busy} step="1" />
        </Field>
        {action === 'issue' && (
          <>
            <Field label="Employee" hint="Employee receiving the stock (optional).">
              <select className="input" value={employee} onChange={(e) => setEmployee(e.target.value)} disabled={busy || loadingRefs}>
                <option value="">None</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.employee_id} — {u.email}</option>)}
              </select>
            </Field>
            <Field label="Department">
              <select className="input" value={department} onChange={(e) => setDepartment(e.target.value)} disabled={busy || loadingRefs}>
                <option value="">None</option>
                {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
        </>)}
        <Field label="Reference" hint="Purchase/reference reference (optional).">
          <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} disabled={busy} />
        </Field>
        <Field label="Reason" required={action === 'adjust'} hint={action === 'adjust' ? 'Required for stock adjustments.' : 'Optional reason.'}>
          <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} rows="2" />
        </Field>
        {fieldMsg(fieldErrors, 'quantity') && <div className="field-error" role="alert">{fieldMsg(fieldErrors, 'quantity')}</div>}
        {fieldMsg(fieldErrors, 'reason') && <div className="field-error" role="alert">{fieldMsg(fieldErrors, 'reason')}</div>}
        {globalError && <div className="error-summary" role="alert">{globalError}</div>}
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Working…' : action === 'receive' ? 'Receive' : action === 'adjust' ? 'Adjust' : 'Apply'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/**
 * Create or edit a stock item. System: create/update restricted to IT staff;
 * delete restricted to System Admins (enforced by the backend).
 */
export function StockItemForm({ id }) {
  const { isStaff } = useAuth();
  const isEdit = !!id;
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState({
    name: '', description: '', sku: '', category: '', unit: 'pcs',
    quantity: '', reorder_threshold: '', preferred_vendor: '', unit_cost: '', is_active: 'true',
  });
  const [vendors, setVendors] = useState([]);
  const [vendorsLoading, setVendorsLoading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get(`/inventory/stock-items/${id}/`);
        const it = r.data;
        setForm({
          name: it.name ?? '', description: it.description ?? '', sku: it.sku ?? '',
          category: it.category ?? '', unit: it.unit ?? 'pcs',
          quantity: String(it.quantity ?? ''), reorder_threshold: String(it.reorder_threshold ?? ''),
          preferred_vendor: String(it.preferred_vendor ?? ''), unit_cost: it.unit_cost != null ? String(it.unit_cost) : '',
          is_active: String(it.is_active ?? true),
        });
      } catch (e) {
        setLoadError(parseApiError(e).global || 'Could not load the stock item.');
      } finally { setLoading(false); }
    })();
  }, [id, isEdit]);

  useEffect(() => {
    (async () => {
      setVendorsLoading(true);
      try {
        const r = await api.get('/assets/vendors/');
        setVendors(r.data.results ?? r.data ?? []);
      } catch { setVendors([]); } finally { setVendorsLoading(false); }
    })();
  }, []);

  const save = async (ev) => {
    ev.preventDefault();
    if (!isStaff || submitting) return;
    setFieldErrors({}); setGlobalError('');
    const payload = {
      name: form.name.trim(), description: form.description.trim(), sku: form.sku.trim(),
      category: form.category.trim(), unit: form.unit,
      quantity: form.quantity ? Number(form.quantity) : 0,
      reorder_threshold: form.reorder_threshold ? Number(form.reorder_threshold) : 0,
      preferred_vendor: form.preferred_vendor ? Number(form.preferred_vendor) : null,
      unit_cost: form.unit_cost ? Number(form.unit_cost) : null,
      is_active: form.is_active === 'true',
    };
    if (!payload.name || !payload.sku) { setGlobalError('Name and SKU are required.'); return; }
    setSubmitting(true);
    try {
      if (isEdit) {
        await api.patch(`/inventory/stock-items/${id}/`, payload);
      } else {
        await api.post('/inventory/stock-items/', payload);
      }
      setTimeout(() => { window.location.hash = '#/inventory/items'; }, 800);
    } catch (e) {
      const p = parseApiError(e);
      setGlobalError(p.global || 'Could not save the stock item.');
      if (p.fields.sku) setFieldErrors((prev) => ({ ...prev, sku: p.fields.sku }));
      if (p.fields.name) setFieldErrors((prev) => ({ ...prev, name: p.fields.name }));
      if (p.fields.quantity) setFieldErrors((prev) => ({ ...prev, quantity: p.fields.quantity }));
    } finally { setSubmitting(false); }
  };

  return (
    <div>
      <PageHeader title={isEdit ? 'Edit stock item' : 'New stock item'} sub="SKU must be unique." />
      {loadError && <div className="error-summary" role="alert">{loadError}</div>}
      {globalError && <div className="error-summary" role="alert">{globalError}</div>}
      <div className="panel">
        <div className="panel-pad">
          <form onSubmit={save} noValidate>
            <div className="row-gap" style={{ gap: 'var(--sp-3)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--sp-2)' }}>
                <Field label="Name" required error={fieldMsg(fieldErrors, 'name')}>
                  <input className="input" value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} disabled={submitting || loading} />
                </Field>
                <Field label="SKU" required error={fieldMsg(fieldErrors, 'sku')}>
                  <input className="input" value={form.sku} onChange={(e) => setForm((p) => ({ ...p, sku: e.target.value }))} disabled={submitting || loading} />
                </Field>
                <Field label="Category">
                  <input className="input" value={form.category} onChange={(e) => setForm((p) => ({ ...p, category: e.target.value }))} disabled={submitting || loading} />
                </Field>
                <Field label="Unit">
                  <select className="input" value={form.unit} onChange={(e) => setForm((p) => ({ ...p, unit: e.target.value }))} disabled={submitting || loading}>
                    {UNIT_CHOICES.map((u) => <option key={u} value={u}>{UNIT_LABELS[u]}</option>)}
                  </select>
                </Field>
                <Field label="Quantity (on-hand)">
                  <input className="input" type="number" min="0" value={form.quantity} onChange={(e) => setForm((p) => ({ ...p, quantity: e.target.value }))} disabled={submitting || loading} />
                </Field>
                <Field label="Reorder threshold">
                  <input className="input" type="number" min="0" value={form.reorder_threshold} onChange={(e) => setForm((p) => ({ ...p, reorder_threshold: e.target.value }))} disabled={submitting || loading} />
                </Field>
                <Field label="Preferred vendor">
                  <select className="input" value={form.preferred_vendor} onChange={(e) => setForm((p) => ({ ...p, preferred_vendor: e.target.value }))} disabled={submitting || vendorsLoading}>
                    <option value="">None</option>
                    {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </select>
                  {vendorsLoading ? <div className="field-hint small">Loading vendors…</div> : null}
                </Field>
                <Field label="Unit cost">
                  <input className="input" type="number" step="0.01" min="0" value={form.unit_cost} onChange={(e) => setForm((p) => ({ ...p, unit_cost: e.target.value }))} disabled={submitting || loading} />
                </Field>
              </div>
              <Field label="Active">
                <select className="input" value={form.is_active} onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.value }))} disabled={submitting || loading}>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </Field>
              {fieldMsg(fieldErrors, 'sku') && <div className="field-error" role="alert">{fieldMsg(fieldErrors, 'sku')}</div>}
              {fieldMsg(fieldErrors, 'name') && <div className="field-error" role="alert">{fieldMsg(fieldErrors, 'name')}</div>}
              {fieldMsg(fieldErrors, 'quantity') && <div className="field-error" role="alert">{fieldMsg(fieldErrors, 'quantity')}</div>}
              <div className="row-end" style={{ marginTop: 'var(--sp-3)' }}>
                <button type="button" className="btn-ghost" onClick={() => { window.location.hash = '#/inventory/items'; }} disabled={submitting}>Cancel</button>
                <button type="submit" className="btn-primary" disabled={submitting || loading || !isStaff}>
                  {submitting ? 'Saving…' : isEdit ? 'Update item' : 'Create item'}
                </button>
                {!isStaff && <span className="muted small">Stock item creation/editing is restricted to IT staff.</span>}
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default Inventory;
