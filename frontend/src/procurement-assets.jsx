import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  DataTable, EmptyState, ErrorSummary, Field, LoadingRows, Modal, PageHeader, Pager,
} from './components';
import {
  PROCUREMENT_ASSET_STATUS_LABELS,
  buildAssetReceiptItemsUrl,
  fetchAll,
  formatDate,
  formatMoney,
  parseFieldErrors,
  procurementCapabilities,
  safeResults,
} from './procurement-utils';

const PAGE_SIZE = 20;

function blankForm(item) {
  return {
    asset_tag: '',
    serial_number: '',
    name: item?.item_name || '',
    category: item?.asset_category ? String(item.asset_category) : '',
    model: '',
    manufacturer: '',
    purchase_date: item?.expected_purchase_date || '',
    purchase_cost: item?.purchase_cost != null ? String(item.purchase_cost) : '',
    warranty_expiry: '',
    location: '',
    department: '',
    notes: '',
  };
}

/**
 * Pending serialized asset registration.
 *
 * Each row is a real `ProcurementAssetReceiptItem` created from an accepted
 * serialized receipt unit. Registration calls the atomic register-asset
 * action; the backend creates and links the Asset, so the source receipt and
 * purchase order are always traceable.
 */
export function ProcurementAssetsPage() {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [active, setActive] = useState(null);
  const [form, setForm] = useState(blankForm(null));
  const [formErrors, setFormErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [response, categoryRows] = await Promise.all([
        api.get(buildAssetReceiptItemsUrl({
          page, page_size: PAGE_SIZE, status: 'pending_registration',
        })),
        fetchAll('/assets/categories/?page_size=100').catch(() => []),
      ]);
      setItems(safeResults(response.data));
      setCount(Number(response.data?.count ?? safeResults(response.data).length));
      setCategories(categoryRows);
    } catch (e) {
      setError(parseFieldErrors(e).global || 'Could not load pending serialized deliveries.');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);

  const openRegister = (item) => {
    setActive(item);
    setForm(blankForm(item));
    setFormErrors({});
    setGlobalError('');
  };

  const submit = async () => {
    if (busy || !active) return;
    const errors = {};
    if (!form.asset_tag.trim()) errors.asset_tag = 'Asset tag is required.';
    if (!form.name.trim()) errors.name = 'Asset name is required.';
    if (!form.category) errors.category = 'Select an asset category.';
    if (form.purchase_cost !== '' && Number(form.purchase_cost) < 0) {
      errors.purchase_cost = 'Purchase cost must be zero or more.';
    }
    setFormErrors(errors);
    if (Object.keys(errors).length) return;

    setBusy(true);
    setGlobalError('');
    try {
      const payload = {
        asset_tag: form.asset_tag.trim(),
        serial_number: form.serial_number.trim(),
        name: form.name.trim(),
        model: form.model.trim(),
        manufacturer: form.manufacturer.trim(),
        location: form.location.trim(),
        notes: form.notes.trim(),
        category: form.category ? Number(form.category) : null,
        department: form.department ? Number(form.department) : null,
        purchase_cost: form.purchase_cost === ''
          ? null : Number(form.purchase_cost).toFixed(2),
        warranty_expiry: form.warranty_expiry || null,
      };
      const response = await api.post(
        `/procurement/asset-receipt-items/${active.id}/register-asset/`, payload,
      );
      setNotice(`Asset ${response.data.asset_tag || form.asset_tag.trim()} registered.`);
      setActive(null);
      await load();
    } catch (e) {
      const status = e?.response?.status;
      const parsed = parseFieldErrors(e);
      if (status === 409) {
        setGlobalError('This unit was already registered. The list has been refreshed.');
        setActive(null);
        await load();
      } else {
        setFormErrors(parsed.fields || {});
        setGlobalError(parsed.global || Object.values(parsed.fields || {})[0] || 'Could not register the asset.');
      }
    } finally {
      setBusy(false);
    }
  };

  if (!caps.canViewProcurement) {
    return <EmptyState title="Access restricted" hint="Procurement is available to IT staff only." />;
  }

  if (loading) return <LoadingRows />;

  if (error) {
    return (
      <div>
        <PageHeader title="Asset registration" />
        <div className="error-summary" role="alert">{error}</div>
        <button type="button" className="btn-primary" onClick={load}>Retry</button>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Pending asset registration"
        sub="One asset per accepted serialized unit, linked to its receipt and purchase order."
        actions={(
          <div className="row-gap">
            <a className="btn-ghost" href="#/procurement">Overview</a>
            <button type="button" className="btn-ghost" onClick={load}>Refresh</button>
          </div>
        )}
      />

      {notice ? <div className="success-summary" role="status">{notice}</div> : null}
      {!caps.canRegisterProcurementAssets ? (
        <div className="error-summary" role="alert">
          Your role can view pending assets but cannot register them.
        </div>
      ) : null}

      <p className="small muted">
        Pending units come from accepted serialized quantities on recorded goods receipts.
        Vendor, purchase date and purchase cost are inherited from the order and receipt.
      </p>

      {items.length === 0 ? (
        <EmptyState
          title="Nothing awaiting asset registration."
          hint="Accepted serialized deliveries will appear here."
        />
      ) : (
        <>
          <DataTable
            columns={[
              { key: 'po', label: 'Purchase order', render: (r) => <a href={`#/procurement/orders/${r.purchase_order}`}>{r.po_number}</a> },
              { key: 'receipt', label: 'Goods receipt', render: (r) => <a href={`#/procurement/receipts/${r.goods_receipt}`}>{r.gr_number}</a> },
              { key: 'vendor', label: 'Vendor', render: (r) => r.vendor_name ?? '—' },
              { key: 'item', label: 'Asset item', render: (r) => <span className="row-title">{r.item_name}</span> },
              { key: 'sequence', label: 'Unit' },
              { key: 'purchase_cost', label: 'Unit cost', render: (r) => formatMoney(r.purchase_cost) },
              { key: 'expected_purchase_date', label: 'Received', render: (r) => formatDate(r.expected_purchase_date) },
              { key: 'status', label: 'Status', render: (r) => PROCUREMENT_ASSET_STATUS_LABELS[r.status] ?? r.status },
              {
                key: 'actions',
                label: 'Actions',
                render: (r) => (
                  <button
                    type="button" className="btn-small"
                    onClick={() => openRegister(r)}
                    disabled={!caps.canRegisterProcurementAssets}
                  >
                    Register asset
                  </button>
                ),
              },
            ]}
            rows={items}
            keyOf={(r) => `asset-item-${r.id}`}
            emptyTitle="Nothing pending."
            emptyHint=""
          />
          <Pager
            count={count}
            hasPrev={currentPage > 1}
            hasNext={currentPage < pageCount}
            onPrev={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() => setPage((p) => Math.min(pageCount, p + 1))}
            busy={loading}
            pageLabel={`Page ${currentPage} of ${pageCount}`}
          />
        </>
      )}

      {active ? (
        <Modal title="Register asset" onClose={() => { if (!busy) setActive(null); }} size="wide">
          <p className="small" style={{ marginTop: 0 }}>
            From {active.po_number} · {active.gr_number} · vendor {active.vendor_name ?? '—'}
            {' '}· unit {active.sequence}.
          </p>
          <div className="row-gap">
            <Field label="Asset tag" required error={formErrors.asset_tag}>
              <input className="input" value={form.asset_tag} onChange={(e) => setForm((f) => ({ ...f, asset_tag: e.target.value }))} aria-label="Asset tag" />
            </Field>
            <Field label="Serial number" error={formErrors.serial_number}>
              <input className="input" value={form.serial_number} onChange={(e) => setForm((f) => ({ ...f, serial_number: e.target.value }))} aria-label="Serial number" />
            </Field>
          </div>
          <Field label="Asset name" required error={formErrors.name}>
            <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} aria-label="Asset name" />
          </Field>
          <Field label="Category" required error={formErrors.category}>
            <select className="input" value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))} aria-label="Category">
              <option value="">Select a category…</option>
              {categories.filter((c) => c.is_active !== false).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </Field>
          <div className="row-gap">
            <Field label="Manufacturer">
              <input className="input" value={form.manufacturer} onChange={(e) => setForm((f) => ({ ...f, manufacturer: e.target.value }))} aria-label="Manufacturer" />
            </Field>
            <Field label="Model">
              <input className="input" value={form.model} onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))} aria-label="Model" />
            </Field>
          </div>
          <div className="row-gap">
            <Field label="Purchase cost" error={formErrors.purchase_cost}>
              <input type="number" min="0" step="0.01" className="input" value={form.purchase_cost} onChange={(e) => setForm((f) => ({ ...f, purchase_cost: e.target.value }))} aria-label="Purchase cost" />
            </Field>
            <Field label="Warranty expiry" error={formErrors.warranty_expiry}>
              <input type="date" className="input" value={form.warranty_expiry} onChange={(e) => setForm((f) => ({ ...f, warranty_expiry: e.target.value }))} aria-label="Warranty expiry" />
            </Field>
          </div>
          <div className="row-gap">
            <Field label="Location">
              <input className="input" value={form.location} onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))} aria-label="Location" />
            </Field>
            <Field label="Department ID">
              <input type="number" min="1" className="input" value={form.department} onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))} aria-label="Department ID" />
            </Field>
          </div>
          <Field label="Notes">
            <textarea className="input" rows={3} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} aria-label="Notes" />
          </Field>
          <p className="small muted">
            Vendor, purchase date and purchase cost are inherited from the purchase order and
            receipt. Serial numbers and asset tags must be unique — the backend rejects duplicates.
          </p>
          {globalError ? <ErrorSummary parsed={{ global: globalError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setActive(null)} disabled={busy}>Cancel</button>
            <button type="button" className="btn-primary" onClick={submit} disabled={busy}>
              {busy ? 'Registering…' : 'Register asset'}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
