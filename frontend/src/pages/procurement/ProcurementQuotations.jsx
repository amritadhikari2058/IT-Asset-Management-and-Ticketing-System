import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import { ProcurementAttachments } from './ProcurementAttachments';
import {
  Badge, DataTable, EmptyState, ErrorSummary, Field, LoadingRows, Modal, PageHeader,
} from '../../components';
import {
  fetchAll,
  formatMoney,
  parseFieldErrors,
  procurementCapabilities,
} from '../../shared/procurement-utils';

function blankQuotation() {
  return {
    vendor: '',
    quoted_amount: '',
    delivery_days: '',
    warranty: '',
    terms: '',
    notes: '',
  };
}

/** Quotation capture, side-by-side comparison and vendor selection. */
export function PurchaseRequestQuotations({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [request, setRequest] = useState(null);
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(blankQuotation());
  const [errors, setErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selecting, setSelecting] = useState(null);
  const [selectionReason, setSelectionReason] = useState('');
  const [notice, setNotice] = useState('');
  const [attachmentQuoteId, setAttachmentQuoteId] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [requestRes, vendorRows] = await Promise.all([
        api.get(`/procurement/purchase-requests/${id}/`),
        fetchAll('/assets/vendors/?page_size=100').catch(() => []),
      ]);
      setRequest(requestRes.data);
      setVendors(vendorRows.filter((v) => v.is_active !== false));
    } catch (e) {
      const parsed = parseFieldErrors(e);
      setError(parsed.global || 'This purchase request is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const comparison = (request?.quotations || []).map((quote) => ({
    ...quote,
    vendor_name: quote.vendor_detail?.name ?? `Vendor ${quote.vendor}`,
  }));

  const lowest = useMemo(() => {
    if (!comparison.length) return null;
    return comparison.reduce((best, row) => (
      Number(row.quoted_amount) < Number(best.quoted_amount) ? row : best
    ));
  }, [comparison]);

  const fastest = useMemo(() => {
    const withDays = comparison.filter((row) => row.delivery_days !== null && row.delivery_days !== undefined);
    if (!withDays.length) return null;
    return withDays.reduce((best, row) => (
      Number(row.delivery_days) < Number(best.delivery_days) ? row : best
    ));
  }, [comparison]);

  const selected = comparison.find((row) => row.is_selected) || null;
  const attachmentQuote = comparison.find(
    (row) => String(row.id) === String(attachmentQuoteId),
  ) || selected || comparison[0] || null;

  const openCreate = () => {
    setForm(blankQuotation());
    setErrors({});
    setGlobalError('');
    setEditing('new');
  };

  const openEdit = (quote) => {
    setForm({
      vendor: String(quote.vendor ?? ''),
      quoted_amount: String(quote.quoted_amount ?? ''),
      delivery_days: quote.delivery_days ?? '',
      warranty: quote.warranty || '',
      terms: quote.terms || '',
      notes: quote.notes || '',
    });
    setErrors({});
    setGlobalError('');
    setEditing(quote.id);
  };

  const validate = () => {
    const next = {};
    if (!form.vendor) next.vendor = 'Select an active vendor.';
    const amount = Number(form.quoted_amount);
    if (!form.quoted_amount || !Number.isFinite(amount) || amount <= 0) {
      next.quoted_amount = 'Quoted amount must be greater than zero.';
    }
    if (form.delivery_days !== '') {
      const days = Number(form.delivery_days);
      if (!Number.isInteger(days) || days < 0) next.delivery_days = 'Delivery days must be zero or more.';
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const save = async () => {
    if (busy) return;
    if (!validate()) return;
    setBusy(true);
    setGlobalError('');
    try {
      const payload = {
        purchase_request: Number(id),
        vendor: Number(form.vendor),
        quoted_amount: Number(form.quoted_amount).toFixed(2),
        delivery_days: form.delivery_days === '' ? null : Number(form.delivery_days),
        warranty: form.warranty.trim(),
        terms: form.terms.trim(),
        notes: form.notes.trim(),
      };
      if (editing === 'new') {
        await api.post('/procurement/quotations/', payload);
        setNotice('Quotation recorded.');
      } else {
        await api.patch(`/procurement/quotations/${editing}/`, payload);
        setNotice('Quotation updated.');
      }
      setEditing(null);
      await load();
    } catch (e) {
      const parsed = parseFieldErrors(e);
      setErrors(parsed.fields || {});
      setGlobalError(parsed.global || 'Could not save the quotation.');
    } finally {
      setBusy(false);
    }
  };

  const selectVendor = async () => {
    if (busy || !selecting) return;
    setBusy(true);
    setGlobalError('');
    try {
      await api.post(`/procurement/quotations/${selecting.id}/select/`, { reason: selectionReason.trim() });
      setSelecting(null);
      setSelectionReason('');
      setNotice('Vendor selected.');
      await load();
    } catch (e) {
      const parsed = parseFieldErrors(e);
      const status = e?.response?.status;
      setGlobalError(
        status === 403
          ? 'You do not have permission to perform this action.'
          : parsed.global || 'Could not select this vendor.',
      );
      if (status === 409) await load();
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingRows />;

  if (error) {
    return (
      <div>
        <PageHeader title="Quotations" />
        <div className="error-summary" role="alert">{error}</div>
        <button type="button" className="btn-primary" onClick={load}>Retry</button>
      </div>
    );
  }

  if (!request) return null;

  if (!caps.canViewProcurement) {
    return <EmptyState title="Access restricted" hint="Procurement is available to IT staff only." />;
  }

  return (
    <div>
      <PageHeader
        title={`Quotations · ${request.pr_number}`}
        sub="Record vendor offers, compare them and select the winning vendor."
        actions={(
          <div className="row-gap">
            <a className="btn-ghost" href={`#/procurement/requests/${request.id}`}>Back to request</a>
            {caps.canManageQuotations && request.status === 'approved' ? (
              <button type="button" className="btn-primary" onClick={openCreate}>Add quotation</button>
            ) : null}
          </div>
        )}
      />

      {request.status !== 'approved' ? (
        <div className="error-summary" role="alert">
          Quotations can only be recorded for an approved request. This request is {request.status.replace(/_/g, ' ')}.
        </div>
      ) : null}
      {notice ? <div className="success-summary" role="status">{notice}</div> : null}
      {globalError && !editing && !selecting ? <ErrorSummary parsed={{ global: globalError }} /> : null}

      {comparison.length === 0 ? (
        <EmptyState
          title="No quotations recorded."
          hint="Add each vendor's offer, then compare price, delivery and warranty before selecting."
        />
      ) : (
        <>
          <div className="panel">
            <div className="panel-head"><h3>Summary</h3></div>
            <div className="panel-pad">
              <p className="small" style={{ marginTop: 0 }}>
                Lowest total: <strong>{lowest ? `${lowest.vendor_name} — ${formatMoney(lowest.quoted_amount)}` : '—'}</strong>
              </p>
              <p className="small">
                Fastest delivery: <strong>{fastest ? `${fastest.vendor_name} — ${fastest.delivery_days} day(s)` : '—'}</strong>
              </p>
              <p className="small">
                Selected vendor: <strong>{selected ? selected.vendor_name : 'None selected'}</strong>
              </p>
              {selected?.selection_reason ? (
                <p className="small muted">Selection reason: {selected.selection_reason}</p>
              ) : null}
              <p className="small muted">
                Price is only one selection factor. Delivery, compatibility, warranty, support and
                approved specifications should also be reviewed.
              </p>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <h3>Comparison</h3>
            <DataTable
              columns={[
                { key: 'vendor_name', label: 'Vendor', render: (r) => <span className="row-title">{r.vendor_name}</span> },
                { key: 'quoted_amount', label: 'Quoted amount', render: (r) => formatMoney(r.quoted_amount) },
                { key: 'delivery_days', label: 'Delivery days', render: (r) => r.delivery_days ?? '—' },
                { key: 'warranty', label: 'Warranty', render: (r) => r.warranty || '—' },
                { key: 'terms', label: 'Payment / delivery terms', render: (r) => r.terms || '—' },
                {
                  key: 'state',
                  label: 'Selection',
                  render: (r) => (r.is_selected
                    ? <Badge kind="status" value="approved" label="Selected" />
                    : 'Not selected'),
                },
                {
                  key: 'actions',
                  label: 'Actions',
                  render: (r) => (
                    <div className="row-gap">
                      {caps.canManageQuotations ? (
                        <button type="button" className="btn-ghost btn-small" onClick={() => openEdit(r)}>Edit</button>
                      ) : null}
                      {caps.canSelectProcurementVendor && request.status === 'approved' ? (
                        <button
                          type="button" className="btn-small"
                          onClick={() => { setSelectionReason(''); setGlobalError(''); setSelecting(r); }}
                          disabled={r.is_selected}
                        >
                          Select vendor
                        </button>
                      ) : null}
                    </div>
                  ),
                },
              ]}
              rows={comparison}
              keyOf={(r) => `quote-${r.id}`}
              emptyTitle="No quotations."
              emptyHint=""
            />
          </div>

          <div style={{ marginTop: 24 }}>
            <h3>Quotation documents</h3>
            <Field label="Quotation">
              <select
                className="input"
                value={attachmentQuote ? String(attachmentQuote.id) : ''}
                onChange={(e) => setAttachmentQuoteId(e.target.value)}
                aria-label="Quotation for attachments"
              >
                {comparison.map((row) => (
                  <option key={row.id} value={row.id}>{row.vendor_name} — {row.quoted_amount}</option>
                ))}
              </select>
            </Field>
            {attachmentQuote ? (
              <ProcurementAttachments
                parentType="quotation"
                parentId={attachmentQuote.id}
                canUpload={caps.canManageQuotations}
                title={`Attachments · ${attachmentQuote.vendor_name}`}
              />
            ) : null}
          </div>

          <div style={{ marginTop: 24 }}>
            <h3>Quotation amounts by vendor</h3>
            <div role="img" aria-label="Quotation amount comparison bars">
              {comparison.map((row) => {
                const max = Math.max(...comparison.map((q) => Number(q.quoted_amount) || 0), 1);
                const width = `${Math.round(((Number(row.quoted_amount) || 0) / max) * 100)}%`;
                return (
                  <div key={`bar-${row.id}`} className="field" style={{ marginBottom: 8 }}>
                    <span className="form-label">{row.vendor_name}</span>
                    <div style={{ background: 'var(--neutral-bg, #eee)', height: 10, borderRadius: 4 }}>
                      <div style={{ width, background: 'var(--info, #3b82f6)', height: 10, borderRadius: 4 }} />
                    </div>
                    <div className="small muted">{formatMoney(row.quoted_amount)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {editing ? (
        <Modal
          title={editing === 'new' ? 'Add quotation' : 'Edit quotation'}
          onClose={() => { if (!busy) setEditing(null); }}
          size="wide"
        >
          <Field label="Vendor" required error={errors.vendor}>
            <select
              className="input" value={form.vendor}
              onChange={(e) => setForm((f) => ({ ...f, vendor: e.target.value }))}
              aria-label="Vendor"
            >
              <option value="">Select an active vendor…</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </Field>
          <Field label="Quoted amount" required error={errors.quoted_amount}>
            <input
              type="number" min="0" step="0.01" className="input" value={form.quoted_amount}
              onChange={(e) => setForm((f) => ({ ...f, quoted_amount: e.target.value }))}
              aria-label="Quoted amount"
            />
          </Field>
          <Field label="Delivery days" error={errors.delivery_days}>
            <input
              type="number" min="0" step="1" className="input" value={form.delivery_days}
              onChange={(e) => setForm((f) => ({ ...f, delivery_days: e.target.value }))}
              aria-label="Delivery days"
            />
          </Field>
          <Field label="Warranty">
            <input
              className="input" value={form.warranty}
              onChange={(e) => setForm((f) => ({ ...f, warranty: e.target.value }))}
              aria-label="Warranty"
            />
          </Field>
          <Field label="Payment / delivery terms">
            <textarea
              className="input" rows={2} value={form.terms}
              onChange={(e) => setForm((f) => ({ ...f, terms: e.target.value }))}
              aria-label="Terms"
            />
          </Field>
          <Field label="Notes">
            <textarea
              className="input" rows={2} value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              aria-label="Quotation notes"
            />
          </Field>
          <p className="small muted">
            Totals are recorded exactly as quoted by the vendor. The backend keeps the
            authoritative amount for the purchase order.
          </p>
          {globalError ? <ErrorSummary parsed={{ global: globalError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setEditing(null)} disabled={busy}>Cancel</button>
            <button type="button" className="btn-primary" onClick={save} disabled={busy}>
              {busy ? 'Saving…' : 'Save quotation'}
            </button>
          </div>
        </Modal>
      ) : null}

      {selecting ? (
        <Modal
          title={`Select ${selecting.vendor_detail?.name ?? 'vendor'}`}
          onClose={() => { if (!busy) setSelecting(null); }}
        >
          <p style={{ marginTop: 0 }}>
            Selecting a vendor records your decision with the reason below. Other quotations stay
            recorded but are no longer selected.
          </p>
          <Field label="Selection reason" required>
            <textarea
              className="input" rows={3} value={selectionReason}
              onChange={(e) => setSelectionReason(e.target.value)}
              aria-label="Selection reason"
            />
          </Field>
          {globalError ? <ErrorSummary parsed={{ global: globalError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setSelecting(null)} disabled={busy}>Cancel</button>
            <button
              type="button" className="btn-primary"
              disabled={busy || !selectionReason.trim()}
              onClick={selectVendor}
            >
              {busy ? 'Selecting…' : 'Confirm selection'}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

