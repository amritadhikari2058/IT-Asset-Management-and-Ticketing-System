import { useCallback, useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  DataTable, EmptyState, ErrorSummary, Field, LoadingRows, PageHeader,
} from './components';
import {
  calculateDisplaySubtotal,
  estimateRequestTotal,
  fetchAll,
  formatMoney,
  parseFieldErrors,
  procurementCapabilities,
} from './procurement-utils';

const STEPS = ['Request information', 'Line items', 'Review and save'];

function blankLine() {
  return {
    key: `line-${Math.random().toString(36).slice(2)}`,
    id: null,
    item_name: '',
    description: '',
    quantity: '1',
    estimated_unit_price: '',
    suggested_vendor: '',
    notes: '',
  };
}

function lineErrors(line) {
  const errors = {};
  if (!line.item_name.trim()) errors.item_name = 'Item name is required.';
  const quantity = Number(line.quantity);
  if (!Number.isInteger(quantity) || quantity <= 0) errors.quantity = 'Quantity must be a whole number greater than zero.';
  if (line.estimated_unit_price !== '') {
    const price = Number(line.estimated_unit_price);
    if (!Number.isFinite(price) || price < 0) errors.estimated_unit_price = 'Unit price must be zero or more.';
  }
  return errors;
}

/** Multi-step purchase request wizard. Creates the request first, then its
 *  line items through the real item endpoint. */
export function PurchaseRequestForm({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const isEdit = !!id;
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState('');
  const [vendors, setVendors] = useState([]);
  const [form, setForm] = useState({ reason: '', notes: '' });
  const [lines, setLines] = useState([blankLine()]);
  const [status, setStatus] = useState('draft');
  const [errors, setErrors] = useState({});
  const [lineFieldErrors, setLineFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!isEdit) return;
    setLoading(true);
    setLoadError('');
    try {
      const [requestRes, vendorRows] = await Promise.all([
        api.get(`/procurement/purchase-requests/${id}/`),
        fetchAll('/assets/vendors/?page_size=100').catch(() => []),
      ]);
      const request = requestRes.data;
      setForm({ reason: request.reason || '', notes: request.notes || '' });
      setStatus(request.status);
      setLines((request.items || []).length
        ? request.items.map((item) => ({
          key: `line-${item.id}`,
          id: item.id,
          item_name: item.item_name || '',
          description: item.description || '',
          quantity: String(item.quantity ?? 1),
          estimated_unit_price: item.estimated_unit_price ?? '',
          suggested_vendor: item.suggested_vendor ?? '',
          notes: item.notes || '',
        }))
        : [blankLine()]);
      setVendors(vendorRows.filter((v) => v.is_active !== false));
    } catch (e) {
      setLoadError(parseFieldErrors(e).global || 'Could not load this purchase request.');
    } finally {
      setLoading(false);
    }
  }, [id, isEdit]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  useEffect(() => {
    if (isEdit) return;
    fetchAll('/assets/vendors/?page_size=100')
      .then((rows) => setVendors(rows.filter((v) => v.is_active !== false)))
      .catch(() => setVendors([]));
  }, [isEdit]);

  const estimate = useMemo(() => estimateRequestTotal(lines.map((line) => ({
    quantity: line.quantity,
    estimated_unit_price: line.estimated_unit_price,
    estimated_total: line.estimated_unit_price === ''
      ? ''
      : (Number(line.quantity) * Number(line.estimated_unit_price)).toFixed(2),
  }))), [lines]);

  const lineProblems = useMemo(() => lines.map(lineErrors), [lines]);

  const setLine = (key, field, value) => {
    setLines((rows) => rows.map((row) => (row.key === key ? { ...row, [field]: value } : row)));
  };

  const addLine = () => setLines((rows) => [...rows, blankLine()]);
  const removeLine = (key) => setLines((rows) => (rows.length > 1 ? rows.filter((row) => row.key !== key) : rows));

  const validateRequestInfo = () => {
    const next = {};
    if (!form.reason.trim()) next.reason = 'Business justification is required.';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const validateLines = () => {
    const problems = lines.map(lineErrors);
    const hasProblem = problems.some((p) => Object.keys(p).length > 0);
    setErrors(hasProblem ? { lines: 'Fix the highlighted line items.' } : {});
    return !hasProblem;
  };

  const goNext = () => {
    if (step === 0 && !validateRequestInfo()) return;
    if (step === 1 && !validateLines()) return;
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  };

  const save = async (submitAfter) => {
    if (busy) return;
    if (!validateRequestInfo()) { setStep(0); return; }
    if (!validateLines()) { setStep(1); return; }
    setBusy(true);
    setGlobalError('');
    setErrors({});
    setLineFieldErrors({});
    try {
      const payload = {
        reason: form.reason.trim(),
        notes: form.notes.trim(),
        estimated_total: estimate,
      };
      let requestId = id ? Number(id) : null;
      if (requestId) {
        await api.patch(`/procurement/purchase-requests/${requestId}/`, payload);
      } else {
        const created = await api.post('/procurement/purchase-requests/', payload);
        requestId = created.data.id;
      }

      for (const line of lines) {
        const linePayload = {
          purchase_request: requestId,
          item_name: line.item_name.trim(),
          description: line.description.trim(),
          quantity: Number(line.quantity),
          estimated_unit_price: line.estimated_unit_price === '' ? null : Number(line.estimated_unit_price),
          estimated_total: (Number(line.quantity) * Number(line.estimated_unit_price || 0)).toFixed(2),
          suggested_vendor: line.suggested_vendor === '' ? null : Number(line.suggested_vendor),
          notes: line.notes.trim(),
        };
        if (line.id) {
          await api.patch(`/procurement/purchase-request-items/${line.id}/`, linePayload);
        } else {
          await api.post('/procurement/purchase-request-items/', linePayload);
        }
      }

      if (submitAfter) {
        await api.post(`/procurement/purchase-requests/${requestId}/submit/`, {});
      }
      window.location.hash = `#/procurement/requests/${requestId}`;
    } catch (e) {
      const parsed = parseFieldErrors(e);
      setGlobalError(parsed.global || 'Could not save the purchase request.');
      const fields = parsed.fields || {};
      if (fields.reason || fields.notes || fields.estimated_total) {
        setErrors(fields);
        setStep(0);
      } else if (Object.keys(fields).length) {
        setLineFieldErrors(fields);
        setStep(1);
      }
    } finally {
      setBusy(false);
    }
  };

  if (!caps.canViewProcurement) {
    return <EmptyState title="Access restricted" hint="Procurement is available to IT staff only." />;
  }

  if (loading) return <LoadingRows />;

  if (loadError) {
    return (
      <div>
        <div className="error-summary" role="alert">{loadError}</div>
        <button type="button" className="btn-primary" onClick={load}>Retry</button>
      </div>
    );
  }

  if (isEdit && !['draft', 'returned_for_correction'].includes(status)) {
    return (
      <div>
        <PageHeader title="Edit purchase request" />
        <EmptyState
          title="This request can no longer be edited"
          hint="Only draft requests, or requests returned for correction, can be changed. Create a new request instead."
          action={<a className="btn-primary" href={`#/procurement/requests/${id}`}>Back to request</a>}
        />
      </div>
    );
  }

  const vendorOptions = vendors;

  return (
    <div>
      <PageHeader
        title={isEdit ? 'Edit purchase request' : 'New purchase request'}
        sub={STEPS[step]}
        actions={<a className="btn-ghost" href={isEdit ? `#/procurement/requests/${id}` : '#/procurement/requests'}>Cancel</a>}
      />

      <ol className="row-gap" aria-label="Wizard steps">
        {STEPS.map((label, index) => (
          <li key={label} className={index === step ? 'row-title' : 'small muted'}>
            Step {index + 1}: {label}{index === step ? ' (current)' : ''}
          </li>
        ))}
      </ol>

      {globalError ? <ErrorSummary parsed={{ global: globalError }} /> : null}

      {step === 0 ? (
        <div className="panel">
          <div className="panel-head"><h3>Request information</h3></div>
          <div className="panel-pad">
            <Field label="Business justification" required error={errors.reason}>
              <textarea
                className="input" rows={4} value={form.reason}
                onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
                aria-label="Business justification"
              />
            </Field>
            <Field label="Notes" error={errors.notes} hint="Optional context for approvers and vendors.">
              <textarea
                className="input" rows={3} value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                aria-label="Notes"
              />
            </Field>
            <p className="small muted">
              The request number, requester and approval state are set by the server.
              Department comes from your profile.
            </p>
          </div>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="panel">
          <div className="panel-head"><h3>Line items</h3></div>
          <div className="panel-pad">
            {errors.lines ? <div className="field-error" role="alert">{errors.lines}</div> : null}
            {lines.map((line, index) => {
              const problems = lineProblems[index] || {};
              return (
                <div key={line.key} className="panel" style={{ marginBottom: 12 }}>
                  <div className="panel-head"><h4>Line {index + 1}</h4></div>
                  <div className="panel-pad">
                    <Field label="Item name" required error={problems.item_name}>
                      <input
                        className="input" value={line.item_name}
                        onChange={(e) => setLine(line.key, 'item_name', e.target.value)}
                        aria-label={`Item name line ${index + 1}`}
                      />
                    </Field>
                    <Field label="Description">
                      <textarea
                        className="input" rows={2} value={line.description}
                        onChange={(e) => setLine(line.key, 'description', e.target.value)}
                        aria-label={`Description line ${index + 1}`}
                      />
                    </Field>
                    <div className="row-gap">
                      <Field label="Quantity" required error={problems.quantity}>
                        <input
                          type="number" min="1" step="1" className="input" value={line.quantity}
                          onChange={(e) => setLine(line.key, 'quantity', e.target.value)}
                          aria-label={`Quantity line ${index + 1}`}
                        />
                      </Field>
                      <Field label="Estimated unit price" error={problems.estimated_unit_price}>
                        <input
                          type="number" min="0" step="0.01" className="input" value={line.estimated_unit_price}
                          onChange={(e) => setLine(line.key, 'estimated_unit_price', e.target.value)}
                          aria-label={`Estimated unit price line ${index + 1}`}
                        />
                      </Field>
                      <Field label="Suggested vendor">
                        <select
                          className="input" value={line.suggested_vendor}
                          onChange={(e) => setLine(line.key, 'suggested_vendor', e.target.value)}
                          aria-label={`Suggested vendor line ${index + 1}`}
                        >
                          <option value="">No preference</option>
                          {vendorOptions.map((v) => (
                            <option key={v.id} value={v.id}>{v.name}</option>
                          ))}
                        </select>
                      </Field>
                    </div>
                    <Field label="Line notes">
                      <input
                        className="input" value={line.notes}
                        onChange={(e) => setLine(line.key, 'notes', e.target.value)}
                        aria-label={`Line notes ${index + 1}`}
                      />
                    </Field>
                    {lines.length > 1 ? (
                      <button type="button" className="btn-ghost btn-small" onClick={() => removeLine(line.key)}>
                        Remove line
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
            {Object.entries(lineFieldErrors).length ? (
              <div className="field-error" role="alert">
                {Object.entries(lineFieldErrors).map(([field, msg]) => `${field}: ${msg}`).join(' ')}
              </div>
            ) : null}
            <button type="button" className="btn-ghost" onClick={addLine}>Add another line</button>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="panel">
          <div className="panel-head"><h3>Review</h3></div>
          <div className="panel-pad">
            <div className="field">
              <span className="form-label">Business justification</span>
              <div className="small">{form.reason || '—'}</div>
            </div>
            <div className="field">
              <span className="form-label">Notes</span>
              <div className="small">{form.notes || '—'}</div>
            </div>
            <div className="field">
              <span className="form-label">Estimated total</span>
              <div>{formatMoney(estimate)} <span className="small muted">(informational — the server stores the request total)</span></div>
            </div>
            <div style={{ marginTop: 12 }}>
              <DataTable
                columns={[
                  { key: 'item_name', label: 'Item' },
                  { key: 'quantity', label: 'Quantity' },
                  { key: 'estimated_unit_price', label: 'Unit price', render: (r) => formatMoney(r.estimated_unit_price) },
                  { key: 'line_total', label: 'Line estimate', render: (r) => formatMoney((Number(r.quantity) * Number(r.estimated_unit_price || 0)).toFixed(2)) },
                  {
                    key: 'vendor',
                    label: 'Suggested vendor',
                    render: (r) => vendorOptions.find((v) => String(v.id) === String(r.suggested_vendor))?.name ?? '—',
                  },
                ]}
                rows={lines}
                keyOf={(r) => r.key}
                emptyTitle="No line items."
                emptyHint="Go back and add at least one line."
              />
            </div>
            <p className="small muted">
              Informational line subtotal {formatMoney(calculateDisplaySubtotal(
                lines.map((l) => ({ quantity: l.quantity, estimated_unit_price: l.estimated_unit_price })),
              ))}
              . The backend total remains authoritative.
            </p>
          </div>
        </div>
      ) : null}

      <div className="row-end" style={{ marginTop: 12 }}>
        <button type="button" className="btn-ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" className="btn-primary" onClick={goNext}>Continue</button>
        ) : (
          <>
            <button type="button" className="btn-ghost" onClick={() => save(false)} disabled={busy}>
              {busy ? 'Saving…' : 'Save draft'}
            </button>
            {caps.canCreatePurchaseRequest ? (
              <button type="button" className="btn-primary" onClick={() => save(true)} disabled={busy}>
                {busy ? 'Saving…' : 'Save and submit for approval'}
              </button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
