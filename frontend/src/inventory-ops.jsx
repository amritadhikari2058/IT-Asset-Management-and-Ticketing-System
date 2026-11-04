import { useCallback, useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, EmptyState,
  Field, LoadingRows, Modal, PageHeader, Pager,
} from './components';
import { fieldMsg, parseApiError, fetchPage } from './api-utils';

const RESERVATION_STATUSES = ['active', 'released', 'fulfilled'];
const FULFILLABLE_STATUSES = ['submitted', 'pending_approval', 'approved', 'in_progress', 'pending_employee'];
const MOVEMENT_TYPES = ['receive', 'issue', 'return', 'adjustment', 'damage', 'lost', 'correction', 'reservation', 'release'];

const fmtDateTime = (d) => d ? new Date(d).toLocaleString() : '—';

function availableOf(item) {
  if (!item) return null;
  return item.available != null ? item.available : Number(item.quantity) - Number(item.reserved || 0);
}

/**
 * Stock receiving via purchase receipts: select vendor, capture purchase
 * reference/invoice/dates, add receipt lines (item + quantity + unit cost),
 * confirm, then submit. Backend increases stock and records movements.
 */
export function ReceiveStock({ onComplete }) {
  const { isStaff } = useAuth();
  const [vendors, setVendors] = useState([]);
  const [items, setItems] = useState([]);
  const [vendorsLoading, setVendorsLoading] = useState(false);
  const [form, setForm] = useState({
    vendor: '', purchase_reference: '', invoice_number: '',
    purchase_date: '', received_date: '', notes: '',
  });
  const [lines, setLines] = useState([{ id: 1, stock_item: '', quantity: '', unit_cost: '' }]);
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    (async () => {
      setVendorsLoading(true);
      try {
        const r = await api.get('/assets/vendors/');
        setVendors(r.data.results ?? r.data ?? []);
      } catch { setVendors([]); } finally { setVendorsLoading(false); }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get('/inventory/stock-items/?page_size=100');
        setItems((r.data.results ?? r.data ?? []).filter((i) => i.is_active !== false && !i.is_deleted));
      } catch { setItems([]); }
    })();
  }, []);

  const addLine = () => {
    const max = Math.max(0, ...lines.map((l) => Number(l.id)));
    setLines([...lines, { id: max + 1, stock_item: '', quantity: '', unit_cost: '' }]);
  };
  const removeLine = (id) => { setLines(lines.filter((l) => l.id !== id)); };
  const setLine = (id, field, value) => {
    setLines(lines.map((l) => l.id === id ? { ...l, [field]: value } : l));
  };

  const validate = () => {
    const errors = {};
    if (!form.vendor) errors.vendor = 'A vendor/supplier is required.';
    if (!lines.length) errors.global = 'Add at least one receipt line.';
    else {
      lines.forEach((l, i) => {
        if (!l.stock_item) { errors[`lines_${i}_item`] = 'Select a stock item.'; }
        const q = Number(l.quantity);
        if (!q || q <= 0) { errors[`lines_${i}_qty`] = 'Quantity must be positive.'; }
      });
    }
    return errors;
  };

  const fieldErrorsFrom = (errors) => {
    const fields = {};
    for (const [k, v] of Object.entries(errors)) {
      if (k === 'global') continue;
      fields[k] = v;
    }
    return fields;
  };

  const confirmSubmit = () => {
    const errors = validate();
    if (errors.global || Object.keys(fieldErrorsFrom(errors)).length) {
      setFieldErrors(fieldErrorsFrom(errors)); setGlobalError(errors.global || ''); return;
    }
    setGlobalError(''); setFieldErrors({});
    setConfirmOpen(true);
  };

  const doSubmit = async () => {
    if (submitting) return;
    setSubmitting(true); setGlobalError(''); setOkMsg('');
    try {
      await api.post('/inventory/purchase-receipts/', {
        vendor: Number(form.vendor),
        purchase_reference: form.purchase_reference.trim(),
        invoice_number: form.invoice_number.trim(),
        purchase_date: form.purchase_date || null,
        received_date: form.received_date || null,
        notes: form.notes.trim(),
        lines: lines.map((l) => ({
          stock_item: Number(l.stock_item),
          quantity: Number(l.quantity),
          unit_cost: l.unit_cost ? Number(l.unit_cost) : null,
        })),
      });
      setOkMsg('Purchase receipt created. Stock levels and movements have been updated.');
      setConfirmOpen(false);
      setSubmitting(false);
      if (onComplete) onComplete();
    } catch (e) {
      const p = parseApiError(e);
      setGlobalError(p.global || 'Could not create the purchase receipt.');
      if (p.fields.vendor) setFieldErrors((prev) => ({ ...prev, vendor: p.fields.vendor }));
      setSubmitting(false);
    }
  };

  const lineRows = lines.map((l) => {
    const selected = items.find((i) => i.id === Number(l.stock_item));
    const avail = availableOf(selected);
    return (
      <div key={`line-${l.id}`} className="form-field" style={{ display: 'grid', gridTemplateColumns: '220px 110px 120px auto 40px', gap: 'var(--sp-1)', alignItems: 'end' }}>
        <select className="input" value={l.stock_item} onChange={(e) => setLine(l.id, 'stock_item', e.target.value)} disabled={submitting} aria-label="Stock item">
          <option value="">Select item…</option>
          {items.map((i) => <option key={i.id} value={i.id}>{i.sku} — {i.name}</option>)}
        </select>
        <input className="input" type="number" min="1" value={l.quantity} onChange={(e) => setLine(l.id, 'quantity', e.target.value)} disabled={submitting} placeholder="Qty" aria-label="Quantity" />
        <input className="input" type="number" step="0.01" min="0" value={l.unit_cost} onChange={(e) => setLine(l.id, 'unit_cost', e.target.value)} disabled={submitting} placeholder="Unit cost" aria-label="Unit cost" />
        <span className="cell-muted">{avail != null ? `Available: ${avail}` : '—'}</span>
        <button type="button" className="btn-ghost btn-danger" onClick={() => removeLine(l.id)} disabled={submitting || lines.length === 1} aria-label="Remove line">✕</button>
      </div>
    );
  });

  return (
    <div>
      <PageHeader title="Receive stock" sub="Record a purchase receipt and increase on-hand stock." />
      {!isStaff && <div className="error-summary" role="alert">Receiving stock is restricted to IT staff.</div>}
      {globalError && <div className="error-summary" role="alert">{globalError}</div>}
      {okMsg && <div className="success-summary" role="status">{okMsg}</div>}
      <div className="panel">
        <div className="panel-pad">
          <form noValidate>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--sp-3)' }}>
              <Field label="Vendor / supplier" required error={fieldMsg(fieldErrors, 'vendor')}>
                <select className="input" value={form.vendor} onChange={(e) => setForm((p) => ({ ...p, vendor: e.target.value }))} disabled={submitting || vendorsLoading} aria-label="Vendor">
                  <option value="">Select vendor…</option>
                  {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
                {vendorsLoading ? <div className="field-hint small">Loading vendors…</div> : null}
              </Field>
              <Field label="Purchase reference">
                <input className="input" value={form.purchase_reference} onChange={(e) => setForm((p) => ({ ...p, purchase_reference: e.target.value }))} disabled={submitting} placeholder="e.g. PO-2026-001" aria-label="Purchase reference" />
              </Field>
              <Field label="Invoice number">
                <input className="input" value={form.invoice_number} onChange={(e) => setForm((p) => ({ ...p, invoice_number: e.target.value }))} disabled={submitting} placeholder="Optional" aria-label="Invoice number" />
              </Field>
              <Field label="Purchase date">
                <input className="input" type="date" value={form.purchase_date} onChange={(e) => setForm((p) => ({ ...p, purchase_date: e.target.value }))} disabled={submitting} aria-label="Purchase date" />
              </Field>
              <Field label="Received date">
                <input className="input" type="date" value={form.received_date} onChange={(e) => setForm((p) => ({ ...p, received_date: e.target.value }))} disabled={submitting} aria-label="Received date" />
              </Field>
            </div>
            <Field label="Notes">
              <textarea className="input" value={form.notes} onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))} disabled={submitting} rows="2" placeholder="Optional notes…" aria-label="Notes" />
            </Field>
            <div className="panel-title"><h4>Receipt lines</h4></div>
            <div className="panel-pad" style={{ paddingTop: 0 }}>
              {lineRows.length ? lineRows : <div className="muted small">No lines yet. Add at least one item to receive.</div>}
              <button type="button" className="btn-secondary" onClick={addLine} disabled={submitting}>+ Add line</button>
            </div>
            <Field label="Confirm before submitting">
              <div className="small muted">Submitting will increase on-hand stock for each line and create stock movements. This cannot be undone from the UI.</div>
            </Field>
            <div className="row-end" style={{ marginTop: 'var(--sp-3)' }}>
              <button type="button" className="btn-ghost" onClick={() => { window.location.hash = '#/inventory/items'; }} disabled={submitting}>Cancel</button>
              <button type="button" className="btn-primary" onClick={confirmSubmit} disabled={submitting || !isStaff}>
                {submitting ? 'Submitting…' : 'Confirm & receive stock'}
              </button>
              {!isStaff && <span className="muted small">Restricted to IT staff.</span>}
            </div>
          </form>
        </div>
      </div>
      {confirmOpen && (
        <ConfirmDialog
          title="Confirm purchase receipt?"
          message={`Receive stock across ${lines.length} line(s)? On-hand quantities will increase immediately.`}
          confirmLabel="Receive stock" danger busy={submitting}
          onConfirm={doSubmit}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * Stock reservations: list, create, release and fulfil. Backend enforces
 * available stock on create and status transitions on release/fulfil.
 */
export function Reservations() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [stockItems, setStockItems] = useState([]);
  const [serviceRequests, setServiceRequests] = useState([]);
  const [refsLoading, setRefsLoading] = useState(false);
  const [openCreate, setOpenCreate] = useState(false);
  const [resForm, setResForm] = useState({ stock_item: '', quantity: '', service_request: '' });
  const [resGlobal, setResGlobal] = useState('');
  const [resSubmitting, setResSubmitting] = useState(false);
  const [rowBusy, setRowBusy] = useState(null);
  const [rowConfirm, setRowConfirm] = useState(null);
  const [page, setPage] = useState(1);

  const pageFromUrl = (url) => {
    try { return Number(new URL(url, 'http://localhost').searchParams.get('page')) || 1; } catch { return 1; }
  };

  const loadUrl = useCallback(async (url) => {
    setLoading(true); setListError('');
    try {
      const pg = await fetchPage(url);
      let rows = pg.items;
      if (statusFilter) rows = rows.filter((r) => r.status === statusFilter);
      setItems(rows);
      setCount(statusFilter ? rows.length : pg.count);
      setNext(pg.next); setPrevious(pg.previous);
      setPage(pageFromUrl(url));
    } catch {
      setListError('Could not load reservations.');
    } finally { setLoading(false); }
  }, [statusFilter]);
  useEffect(() => { loadUrl('/inventory/reservations/'); }, [loadUrl]);

  useEffect(() => {
    setRefsLoading(true);
    Promise.all([
      api.get('/inventory/stock-items/?page_size=100').then((r) => setStockItems(r.data.results ?? r.data ?? [])).catch(() => setStockItems([])),
      api.get('/services/requests/?page_size=100').then((r) => setServiceRequests(r.data.results ?? r.data ?? [])).catch(() => setServiceRequests([])),
    ]).finally(() => setRefsLoading(false));
  }, []);

  const runRow = useCallback(async (id, action) => {
    if (rowBusy) return;
    setRowBusy(id);
    try {
      await api.post(`/inventory/reservations/${id}/${action}/`);
      setRowBusy(null);
      setRowConfirm(null);
      await loadUrl('/inventory/reservations/');
    } catch (e) {
      const p = parseApiError(e);
      alert(p.global || `Reservation ${action} failed.`);
      setRowBusy(null);
      setRowConfirm(null);
    }
  }, [rowBusy, loadUrl]);

  const createRes = async (ev) => {
    ev.preventDefault();
    if (resSubmitting) return;
    setResGlobal('');
    const q = Number(resForm.quantity);
    if (!resForm.stock_item || !q || q <= 0) { setResGlobal('Select a stock item and a positive quantity.'); return; }
    if (!resForm.service_request) { setResGlobal('Select a service request.'); return; }
    setResSubmitting(true);
    try {
      await api.post('/inventory/reservations/', {
        stock_item: Number(resForm.stock_item),
        quantity: q,
        service_request: Number(resForm.service_request),
      });
      setResSubmitting(false);
      setOpenCreate(false);
      setResForm({ stock_item: '', quantity: '', service_request: '' });
      await loadUrl('/inventory/reservations/');
    } catch (e) {
      const p = parseApiError(e);
      setResGlobal(p.global || 'Could not create the reservation.');
      setResSubmitting(false);
    }
  };

  return (
    <div>
      <PageHeader title="Stock reservations" sub={count != null ? `${count} reservation${count === 1 ? '' : 's'} in scope` : undefined} actions={<>
        {isStaff && <button type="button" className="btn-primary" onClick={() => setOpenCreate(true)}>+ Reserve stock</button>}
      </>} />
      {listError && <div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl('/inventory/reservations/')}>Retry</button></div>}
      <div className="filter-bar" role="search">
        <div className="field-inline">
          <div className="caption">Status</div>
          <select className="input" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); loadUrl('/inventory/reservations/'); }} aria-label="Filter reservations by status">
            <option value="">All statuses</option>
            {RESERVATION_STATUSES.map((s) => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
          </select>
        </div>
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={5} /></div>
          : items.length === 0 ? (
            <div className="panel-pad"><EmptyState title="No reservations." hint="Reserved stock appears here. IT staff can create reservations against available stock." /></div>
          ) : (
            <>
              <table className="grid">
                <thead>
                  <tr>
                    <th>Stock item</th><th>Quantity</th><th>Status</th><th>Service request</th><th>Created by</th><th>Created</th>
                    {isStaff && <th className="cell-actions">Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {items.map((r) => {
                    const item = stockItems.find((i) => i.id === r.stock_item);
                    return (
                      <tr key={r.id}>
                        <td>{item ? <span className="ellipsis" title={item.name}>{item.name} <span className="cell-muted">({item.sku})</span></span> : `Item #${r.stock_item}`}</td>
                        <td>{r.quantity}</td>
                        <td><Badge kind="status" value={r.status} /></td>
                        <td>{r.service_request ? <a className="row-title" href={`#/service-requests/${r.service_request}`}>SR #{r.service_request}</a> : '—'}</td>
                        <td>{r.created_by_name || `User #${r.created_by}`}</td>
                        <td>{fmtDateTime(r.created_at)}</td>
                        {isStaff && (
                          <td className="cell-actions">
                            {r.status === 'active' && (
                              <>
                                <button type="button" className="btn-small" onClick={() => setRowConfirm({ id: r.id, action: 'release' })} disabled={rowBusy === r.id}>Release</button>{' '}
                                <button type="button" className="btn-small" onClick={() => setRowConfirm({ id: r.id, action: 'fulfil' })} disabled={rowBusy === r.id}>Fulfil</button>
                              </>
                            )}
                            {r.status !== 'active' && <span className="cell-muted">—</span>}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <Pager count={count} pageLabel={count != null ? `Page ${page}` : ''} hasNext={!!next && !statusFilter} hasPrev={!!previous && !statusFilter} busy={loading}
                onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
            </>
          )}
      </div>
      {rowConfirm && (
        <ConfirmDialog
          title={`Reservation ${rowConfirm.action}`}
          message={`Confirm ${rowConfirm.action} of reservation #${rowConfirm.id}?`}
          confirmLabel={`${rowConfirm.action.charAt(0).toUpperCase() + rowConfirm.action.slice(1)} reservation`}
          danger={rowConfirm.action === 'release'} busy={rowBusy === rowConfirm.id}
          onConfirm={() => runRow(rowConfirm.id, rowConfirm.action)}
          onCancel={() => setRowConfirm(null)}
        />
      )}
      {openCreate && (
        <Modal title="Reserve stock" onClose={() => { if (!resSubmitting) setOpenCreate(false); }} size="md">
          <form onSubmit={createRes} noValidate>
            <Field label="Stock item" required>
              <select className="input" value={resForm.stock_item} onChange={(e) => setResForm((p) => ({ ...p, stock_item: e.target.value }))} disabled={resSubmitting || refsLoading} aria-label="Stock item">
                <option value="">Select item…</option>
                {stockItems.map((i) => {
                  const avail = availableOf(i);
                  return <option key={i.id} value={i.id}>{i.sku} — {i.name} (available {avail != null ? avail : '?'})</option>;
                })}
              </select>
              {refsLoading ? <div className="field-hint small">Loading items…</div> : null}
            </Field>
            <Field label="Quantity" required>
              <input className="input" type="number" min="1" value={resForm.quantity} onChange={(e) => setResForm((p) => ({ ...p, quantity: e.target.value }))} disabled={resSubmitting} aria-label="Quantity" />
            </Field>
            <Field label="Service request" required>
              <select className="input" value={resForm.service_request} onChange={(e) => setResForm((p) => ({ ...p, service_request: e.target.value }))} disabled={resSubmitting || refsLoading} aria-label="Service request">
                <option value="">Select request…</option>
                {serviceRequests.map((sr) => <option key={sr.id} value={sr.id}>{sr.request_number} — {sr.catalogue_item_name || 'Service request'}</option>)}
              </select>
            </Field>
            {resGlobal && <div className="field-error" role="alert">{resGlobal}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => { if (!resSubmitting) setOpenCreate(false); }} disabled={resSubmitting}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={resSubmitting || !isStaff}>{resSubmitting ? 'Reserving…' : 'Reserve'}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/**
 * Inventory transaction history (stock movements). Read-only audit trail.
 * Search/filter by item, type and date; pagination over the fetched window.
 */
export function TransactionHistory() {
  const [movements, setMovements] = useState([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [stockItems, setStockItems] = useState([]);
  const [f, setF] = useState({ stock_item: '', type: '', date_from: '', date_to: '' });
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 25;

  const load = useCallback(async () => {
    setLoading(true); setListError('');
    try {
      const p = new URLSearchParams();
      if (f.stock_item) p.set('stock_item', f.stock_item);
      const r = await api.get(`/inventory/stock-items/movements/?${p.toString()}`);
      const data = Array.isArray(r.data) ? r.data : (r.data.results ?? []);
      setMovements(data);
    } catch {
      setListError('Could not load stock movements.');
    } finally { setLoading(false); }
  }, [f.stock_item]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api.get('/inventory/stock-items/?page_size=100').then((r) => setStockItems(r.data.results ?? r.data ?? [])).catch(() => setStockItems([]));
  }, []);

  const filtered = useMemo(() => {
    return movements.filter((m) => {
      if (f.type && m.movement_type !== f.type) return false;
      if (f.date_from && m.created_at < f.date_from) return false;
      if (f.date_to && m.created_at > f.date_to) return false;
      return true;
    });
  }, [movements, f.type, f.date_from, f.date_to]);

  const paged = useMemo(() => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [filtered, page]);

  const apply = (patch) => { setF((prev) => ({ ...prev, ...patch })); setPage(1); };

  return (
    <div>
      <PageHeader title="Stock movement history" sub="Read-only audit trail of stock movements. Backend rejects edits to historical movements." />
      {listError && <div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={load}>Retry</button></div>}
      <div className="filter-bar" role="search">
        <div className="field-inline">
          <div className="caption">Item</div>
          <select className="input" value={f.stock_item} onChange={(e) => apply({ stock_item: e.target.value })} aria-label="Filter by stock item">
            <option value="">All items</option>
            {stockItems.map((i) => <option key={i.id} value={i.id}>{i.sku} — {i.name}</option>)}
          </select>
        </div>
        <div className="field-inline">
          <div className="caption">Type</div>
          <select className="input" value={f.type} onChange={(e) => apply({ type: e.target.value })} aria-label="Filter by movement type">
            <option value="">All types</option>
            {MOVEMENT_TYPES.map((t) => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
          </select>
        </div>
        <div className="field-inline">
          <div className="caption">From</div>
          <input className="input" type="date" value={f.date_from} onChange={(e) => apply({ date_from: e.target.value })} aria-label="From date" />
        </div>
        <div className="field-inline">
          <div className="caption">To</div>
          <input className="input" type="date" value={f.date_to} onChange={(e) => apply({ date_to: e.target.value })} aria-label="To date" />
        </div>
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : filtered.length === 0 ? (
            <div className="panel-pad"><EmptyState title="No stock movements." hint="Movements appear here when stock is received, issued, reserved or adjusted." /></div>
          ) : (
            <>
              <table className="grid">
                <thead>
                  <tr><th>Stock item</th><th>Type</th><th>Qty change</th><th>Balance before → after</th><th>Reference</th><th>Performed by</th><th>When</th><th>Notes</th></tr>
                </thead>
                <tbody>
                  {paged.map((m) => {
                    const item = stockItems.find((i) => i.id === m.stock_item);
                    return (
                      <tr key={m.id}>
                        <td>{item ? <span className="ellipsis" title={item.name}>{item.name}</span> : `Item #${m.stock_item}`}</td>
                        <td><Badge kind="status" value={m.movement_type} /></td>
                        <td>{m.quantity >= 0 ? `+${m.quantity}` : m.quantity}</td>
                        <td>{m.previous_balance} → {m.new_balance}</td>
                        <td>{m.reference || '—'}</td>
                        <td>{m.recorded_by_name || `User #${m.recorded_by}`}</td>
                        <td>{fmtDateTime(m.created_at)}</td>
                        <td>{m.reason || '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="pager">
                <span className="page-count">{filtered.length} {filtered.length === 1 ? 'movement' : 'movements'}</span>
                <span className="spacer" />
                <button type="button" className="btn-small" disabled={page === 1 || loading} onClick={() => setPage((p) => p - 1)}>&larr; Prev</button>
                <span className="muted small">Page {page} of {Math.ceil(filtered.length / PAGE_SIZE) || 1}</span>
                <button type="button" className="btn-small" disabled={page * PAGE_SIZE >= filtered.length || loading} onClick={() => setPage((p) => p + 1)}>Next &rarr;</button>
              </div>
            </>
          )}
      </div>
    </div>
  );
}

/**
 * Fulfil a service request from available inventory. Backend prevents
 * duplicate fulfilment and rejects insufficient stock.
 */
export function FulfilServiceRequest() {
  const { isStaff } = useAuth();
  const [requests, setRequests] = useState([]);
  const [stockItems, setStockItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [refsLoading, setRefsLoading] = useState(false);
  const [fulfilOpen, setFulfilOpen] = useState(null);
  const [fulfilForm, setFulfilForm] = useState({ stock_item: '', quantity: '' });
  const [fulfilGlobal, setFulfilGlobal] = useState('');
  const [fulfilSubmitting, setFulfilSubmitting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setListError('');
    try {
      const r = await api.get('/services/requests/');
      const rows = r.data.results ?? r.data ?? [];
      setRequests(rows.filter((sr) => FULFILLABLE_STATUSES.includes(sr.status)));
    } catch {
      setListError('Could not load service requests.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    setRefsLoading(true);
    api.get('/inventory/stock-items/?page_size=100').then((r) => setStockItems((r.data.results ?? r.data ?? []).filter((i) => i.is_active !== false && !i.is_deleted))).catch(() => setStockItems([]));
  }, []);

  const selectedItem = useMemo(() => stockItems.find((i) => i.id === Number(fulfilForm.stock_item)), [stockItems, fulfilForm.stock_item]);
  const avail = availableOf(selectedItem);

  const openFulfil = (sr) => {
    setFulfilOpen(sr);
    setFulfilForm({ stock_item: '', quantity: '' });
    setFulfilGlobal('');
  };

  const doFulfil = async (ev) => {
    ev.preventDefault();
    if (!fulfilOpen || fulfilSubmitting) return;
    setFulfilGlobal('');
    const sr = fulfilOpen;
    const q = Number(fulfilForm.quantity);
    if (!fulfilForm.stock_item || !q || q <= 0) { setFulfilGlobal('Select a stock item and a positive quantity.'); return; }
    if (avail != null && q > avail) { setFulfilGlobal(`Only ${avail} unit(s) available for ${selectedItem.name}.`); return; }
    setFulfilSubmitting(sr.id);
    try {
      await api.post('/inventory/fulfil-service-request/', {
        service_request: sr.id,
        stock_item: Number(fulfilForm.stock_item),
        quantity: q,
      });
      setFulfilSubmitting(null);
      setFulfilOpen(null);
      await load();
    } catch (e) {
      const p = parseApiError(e);
      setFulfilGlobal(p.global || 'Fulfilment failed.');
      setFulfilSubmitting(null);
    }
  };

  return (
    <div>
      <PageHeader title="Fulfil service request" sub="Issue stock from inventory against a service request. IT staff only." />
      {!isStaff && <div className="error-summary" role="alert">Fulfilment is restricted to IT staff.</div>}
      {listError && <div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={load}>Retry</button></div>}
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={5} /></div>
          : requests.length === 0 ? (
            <div className="panel-pad"><EmptyState title="No requests ready for fulfilment." hint="Service requests awaiting stock fulfilment appear here." /></div>
          ) : (
            <table className="grid">
              <thead>
                <tr><th>Number</th><th>Service</th><th>Requester</th><th>Status</th><th>Submitted</th>
                  {isStaff && <th className="cell-actions">Fulfil</th>}
                </tr>
              </thead>
              <tbody>
                {requests.map((sr) => (
                  <tr key={sr.id}>
                    <td>{sr.request_number}</td>
                    <td>{sr.catalogue_item_name || '—'}</td>
                    <td>{sr.requester_name || `User #${sr.requester}`}</td>
                    <td><Badge kind="status" value={sr.status} /></td>
                    <td>{fmtDateTime(sr.submitted_at)}</td>
                    {isStaff && (
                      <td className="cell-actions">
                        <button type="button" className="btn-small" onClick={() => openFulfil(sr)} disabled={fulfilSubmitting === sr.id}>
                          {fulfilSubmitting === sr.id ? 'Fulfilling…' : 'Fulfil'}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
      {fulfilOpen && (
        <Modal title={`Fulfil ${fulfilOpen.request_number}`} onClose={() => { if (!fulfilSubmitting) setFulfilOpen(null); }} size="md">
          <form onSubmit={doFulfil} noValidate>
            <div className="panel-title"><h4>Available stock</h4></div>
            <div className="panel-pad" style={{ paddingTop: 0 }}>
              <select className="input" value={fulfilForm.stock_item} onChange={(e) => setFulfilForm((p) => ({ ...p, stock_item: e.target.value }))} disabled={fulfilSubmitting || refsLoading} aria-label="Stock item">
                <option value="">Select stock item…</option>
                {stockItems.map((i) => {
                  const a = availableOf(i);
                  return <option key={i.id} value={i.id}>{i.sku} — {i.name} (available {a != null ? a : '?'})</option>;
                })}
              </select>
              {refsLoading ? <div className="field-hint small">Loading items…</div> : null}
              {selectedItem && (
                <div className="small muted">Available: {avail} {UNIT_LABEL(selectedItem.unit)} of {selectedItem.name}</div>
              )}
            </div>
            <Field label="Quantity" required>
              <input className="input" type="number" min="1" value={fulfilForm.quantity} onChange={(e) => setFulfilForm((p) => ({ ...p, quantity: e.target.value }))} disabled={fulfilSubmitting} aria-label="Quantity" />
            </Field>
            {fulfilGlobal && <div className="field-error" role="alert">{fulfilGlobal}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => { if (!fulfilSubmitting) setFulfilOpen(null); }} disabled={fulfilSubmitting}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={fulfilSubmitting || !isStaff}>{fulfilSubmitting ? 'Fulfilling…' : 'Fulfil request'}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );

  function UNIT_LABEL(unit) {
    const labels = { pcs: 'pcs', box: 'box', set: 'set', unit: 'unit', meter: 'meter', other: 'other' };
    return labels[unit] ?? unit;
  }
}