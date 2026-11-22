import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from './auth';
import { AccessDenied, Badge, Field, DataTable, Pager, PageHeader, Modal, ConfirmDialog, UserSelect, PageSizeSelector } from './components';
import { fetchPage, parseApiError } from './api-utils';
import api from './api';
import {
  licensingCapabilities,
  buildAllocationListUrl,
  ALLOCATION_TYPE_LABELS,
  ALLOCATION_STATUS_LABELS,
} from './licensing-utils';
import { HistoryList } from './license-history';

const RELEASABLE_STATUSES = ['reserved', 'assigned', 'active', 'suspended', 'expired'];

function LicenseAllocationsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  // Page-size preference persisted in localStorage; fall back to DRF default 20.
  const [pageSize, setPageSize] = useState(() => {
    if (typeof window === 'undefined') return 20;
    try {
      const saved = window.localStorage.getItem('itdesk.pageSize');
      const n = Number(saved);
      return saved && Number.isFinite(n) && n > 0 && n <= 100 ? n : 20;
    } catch {
      return 20;
    }
  });
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page] = useState(1); // pager loads absolute next/previous URLs
  const [lastUrl, setLastUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [f, setF] = useState({ search: '', status: '', allocation_type: '', agreement: '' });
  const [busyId, setBusyId] = useState(null);

  // Release state
  const [releaseTarget, setReleaseTarget] = useState(null);
  const [releaseReason, setReleaseReason] = useState('');
  const [releaseBusy, setReleaseBusy] = useState(false);
  const [releaseError, setReleaseError] = useState('');

  // History state
  const [historyTarget, setHistoryTarget] = useState(null);
  const [historyItems, setHistoryItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  // Offboarding state
  const [offboardUserId, setOffboardUserId] = useState('');
  const [offboardReason, setOffboardReason] = useState('');
  const [offboardPreview, setOffboardPreview] = useState(null);
  const [offboardPreviewLoading, setOffboardPreviewLoading] = useState(false);
  const [offboardPreviewError, setOffboardPreviewError] = useState('');
  const [offboardBusy, setOffboardBusy] = useState(false);
  const [offboardError, setOffboardError] = useState('');
  const [offboardResult, setOffboardResult] = useState(null);
  const [confirmOffboard, setConfirmOffboard] = useState(false);

  const builtUrl = useMemo(() => buildAllocationListUrl(f, null, page, pageSize), [f, page, pageSize]);

  const loadUrl = async (url) => {
    const requestId = ++requestIdRef.current;
    setLoading(true); setError('');
    try {
      const pg = await fetchPage(url);
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setItems(pg.items ?? []); setCount(pg.count ?? 0); setNext(pg.next ?? null); setPrevious(pg.previous ?? null);
      setLastUrl(url);
    } catch (e) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setError(parseApiError(e).global || 'Could not load allocations.');
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) setLoading(false);
    }
  };
  // Reload whichever page the user is actually on (Pager loads absolute
  // next/previous URLs, so rebuilding from `page` would jump back to page 1).
  const reload = () => loadUrl(lastUrl || builtUrl);

  useEffect(() => {
    if (!caps.canViewAllocations) return undefined;
    const t = setTimeout(() => loadUrl(builtUrl), 250);
    return () => clearTimeout(t);
  }, [builtUrl, caps.canViewAllocations]);

  // Persist page-size preference without unnecessary writes
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      if (window.localStorage.getItem('itdesk.pageSize') !== String(pageSize)) {
        window.localStorage.setItem('itdesk.pageSize', String(pageSize));
      }
    } catch {
      // ignore storage failures
    }
  }, [pageSize]);

  const doAction = async (row, action, body = {}) => {
    if (busyId) return;
    const ref = row.allocation_reference || `#${row.id}`;
    setBusyId(row.id); setError(''); setMessage('');
    try {
      await api.post(`/licensing/allocations/${row.id}/${action}/`, body);
      setMessage(`Allocation ${ref}: ${action} completed.`);
      await reload();
    } catch (e) {
      setError(parseApiError(e).global || 'Action failed.');
    } finally { setBusyId(null); }
  };

  const openRelease = (row) => {
    setReleaseTarget(row);
    setReleaseReason('');
    setReleaseError('');
  };
  const closeRelease = () => { if (!releaseBusy) { setReleaseTarget(null); setReleaseReason(''); setReleaseError(''); } };
  const submitRelease = async () => {
    if (!releaseTarget || releaseBusy) return;
    setReleaseBusy(true); setReleaseError('');
    try {
      await api.post(`/licensing/allocations/${releaseTarget.id}/release/`, { reason: releaseReason.trim() });
      const ref = releaseTarget.allocation_reference || `#${releaseTarget.id}`;
      setMessage(`Allocation ${ref} released. The seat was returned to ${releaseTarget.agreement_number || 'its agreement'}.`);
      setReleaseTarget(null);
      setReleaseReason('');
      await reload();
    } catch (e) {
      setReleaseError(parseApiError(e).global || 'Release failed.');
    } finally {
      setReleaseBusy(false);
    }
  };

  const openHistory = async (row) => {
    setHistoryTarget(row);
    setHistoryItems([]);
    setHistoryError('');
    setHistoryLoading(true);
    try {
      const r = await api.get(`/licensing/allocations/${row.id}/history/`);
      setHistoryItems(Array.isArray(r.data) ? r.data : (r.data?.results || []));
    } catch (e) {
      setHistoryError(e?.response?.status === 403
        ? 'You do not have permission to view this allocation history.'
        : (parseApiError(e).global || 'Could not load history.'));
    } finally {
      setHistoryLoading(false);
    }
  };
  const closeHistory = () => { setHistoryTarget(null); setHistoryItems([]); setHistoryError(''); };

  const changeOffboardUser = (value) => {
    if (offboardBusy) return;
    setOffboardUserId(value);
    // A preview is only valid for the employee it was requested for: drop any
    // stale preview/result so a different employee can never be offboarded.
    setOffboardPreview(null);
    setOffboardResult(null);
    setOffboardPreviewError('');
    setOffboardError('');
  };

  const requestOffboardPreview = async () => {
    if (!offboardUserId || offboardPreviewLoading) return;
    setOffboardPreviewLoading(true);
    setOffboardPreviewError('');
    setOffboardPreview(null);
    setOffboardResult(null);
    try {
      const r = await api.get(`/licensing/allocations/offboarding-preview/?user=${encodeURIComponent(offboardUserId)}`);
      setOffboardPreview(r.data);
    } catch (e) {
      setOffboardPreviewError(parseApiError(e).global || 'Could not load the offboarding preview.');
    } finally {
      setOffboardPreviewLoading(false);
    }
  };

  const executeOffboard = async () => {
    // Execution is only allowed right after a preview was loaded for this user;
    // opening a preview alone never revokes anything.
    if (offboardBusy || !offboardPreview) return;
    setOffboardBusy(true);
    setOffboardError('');
    try {
      const body = { user_id: Number(offboardUserId) };
      if (offboardReason.trim()) body.reason = offboardReason.trim();
      const r = await api.post('/licensing/allocations/offboard/', body);
      setOffboardResult(r.data);
      setConfirmOffboard(false);
      setOffboardPreview(null);
      setMessage(`Offboarding finished: ${r.data.revoked_count} of ${r.data.total_active} allocation(s) reclaimed.`);
      await reload();
    } catch (e) {
      setOffboardError(parseApiError(e).global || 'Offboarding failed.');
    } finally {
      setOffboardBusy(false);
    }
  };

  const columns = [
    { key: 'product_name', label: 'Product' },
    { key: 'agreement_number', label: 'Agreement' },
    { key: 'allocation_type', label: 'Type', render: (v) => ALLOCATION_TYPE_LABELS[v.allocation_type] || v.allocation_type },
    { key: 'user_email', label: 'User' },
    { key: 'asset_tag', label: 'Asset' },
    { key: 'status', label: 'Status', render: (v) => <Badge kind="status" value={ALLOCATION_STATUS_LABELS[v.status] || v.status} /> },
    { key: 'assigned_at', label: 'Assigned' },
    { key: 'last_verified_at', label: 'Verified' },
    { key: 'actions', label: 'Actions', render: (v) => {
      const rowBusy = busyId === v.id;
      const terminal = ['revoked', 'expired'].includes(v.status);
      return (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {!['active', 'revoked', 'expired'].includes(v.status) && (
            <button className="btn btn-sm btn-outline" disabled={rowBusy}
              onClick={() => { if (window.confirm('Activate this allocation? Entitlement capacity will be checked and the action is audited.')) doAction(v, 'activate'); }}>
              Activate
            </button>
          )}
          {!['suspended', 'revoked', 'expired'].includes(v.status) && (
            <button className="btn btn-sm btn-outline" disabled={rowBusy}
              onClick={() => { const r = window.prompt('Suspension reason (capacity is released):'); if (r && r.trim()) doAction(v, 'suspend', { reason: r.trim() }); }}>
              Suspend
            </button>
          )}
          <button className="btn btn-sm btn-outline" disabled={rowBusy} onClick={() => doAction(v, 'verify')}>Verify</button>
          {!terminal && RELEASABLE_STATUSES.includes(v.status) && (
            <button className="btn btn-sm btn-outline" disabled={rowBusy} onClick={() => openRelease(v)}>Release</button>
          )}
          <button className="btn btn-sm btn-outline" disabled={rowBusy} onClick={() => openHistory(v)}>History</button>
          {v.status !== 'revoked' && (
            <button className="btn btn-sm btn-outline danger" disabled={rowBusy}
              onClick={() => { const r = window.prompt('Revocation reason:'); if (r && r.trim()) doAction(v, 'revoke', { reason: r.trim() }); }}>
              Revoke
            </button>
          )}
        </div>
      );
    } },
  ];
  if (!caps.canViewAllocations) return <AccessDenied />;

  const previewAllocations = offboardPreview?.allocations || [];
  const previewCount = offboardPreview?.count ?? previewAllocations.length;
  const offboardFailures = (offboardResult?.results || []).filter((r) => !r.success);

  return (
    <div className="license-allocations-page">
      <PageHeader title="License Allocations" />
      {message && <div className="alert alert-success" role="status">{message}</div>}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Search" required={false}><input className="input" value={f.search} onChange={(e) => setF({ ...f, search: e.target.value })} /></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(ALLOCATION_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Type" required={false}><select className="input" value={f.allocation_type} onChange={(e) => setF({ ...f, allocation_type: e.target.value })}><option value="">All</option>{Object.entries(ALLOCATION_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      {loading
        ? <p className="muted" role="status">Loading allocations…</p>
        : <DataTable columns={columns} rows={items} keyOf={(r) => r.id} emptyTitle="No allocations found" />}
      <PageSizeSelector value={pageSize} onChange={setPageSize} />{count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}

      {/* Offboarding workflow: preview first, explicit confirmation before execution */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-body">
          <h5>Employee offboarding</h5>
          <p className="text-muted small">
            Preview the seats that would be reclaimed for an employee (named-user seats plus
            device seats on assets assigned to them). Opening a preview does not change anything;
            seats are only revoked when you confirm execution.
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <UserSelect value={offboardUserId} onChange={changeOffboardUser} disabled={offboardBusy} label="Employee" />
            <button className="btn btn-outline" onClick={requestOffboardPreview}
              disabled={offboardPreviewLoading || offboardBusy || !offboardUserId}>
              {offboardPreviewLoading ? 'Loading preview…' : 'Preview affected seats'}
            </button>
          </div>
          {offboardPreviewError && <div className="alert alert-danger" role="alert" style={{ marginTop: 8 }}>{offboardPreviewError}</div>}
          {offboardPreview && (
            <div style={{ marginTop: 12 }} data-testid="offboarding-preview">
              <p>
                {previewCount === 0
                  ? 'This employee holds no active or reserved allocations.'
                  : `${previewCount} active or reserved allocation(s) would be revoked. Capacity is returned to each agreement and every revocation is audited.`}
              </p>
              {previewAllocations.length > 0 && (
                <table className="table table-sm">
                  <thead><tr><th>Product</th><th>Agreement</th><th>Reference</th><th>Type</th><th>Status</th></tr></thead>
                  <tbody>
                    {previewAllocations.map((a) => (
                      <tr key={a.id}>
                        <td>{a.product_name}</td>
                        <td>{a.agreement_number}</td>
                        <td>{a.allocation_reference}</td>
                        <td>{ALLOCATION_TYPE_LABELS[a.allocation_type] || a.allocation_type || '—'}</td>
                        <td>{ALLOCATION_STATUS_LABELS[a.status] || a.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {previewCount > 0 && (
                <>
                  <Field label="Offboarding reason (optional)" hint="Stored on each revoked allocation and in the audit history.">
                    <textarea className="input" rows={2} value={offboardReason}
                      onChange={(e) => setOffboardReason(e.target.value)} disabled={offboardBusy} />
                  </Field>
                  <button className="btn btn-danger" style={{ marginTop: 8 }} onClick={() => setConfirmOffboard(true)}
                    disabled={offboardBusy}>
                    {offboardBusy ? 'Working…' : 'Execute offboarding…'}
                  </button>
                </>
              )}
            </div>
          )}
          {offboardError && <div className="alert alert-danger" role="alert" style={{ marginTop: 8 }}>{offboardError}</div>}
          {offboardResult && (
            <div style={{ marginTop: 8 }}>
              <div className="alert alert-success" role="status">
                Revoked {offboardResult.revoked_count} of {offboardResult.total_active} allocation(s).
              </div>
              {offboardFailures.length > 0 && (
                <div className="alert alert-warning" role="alert">
                  {offboardFailures.length} allocation(s) could not be revoked:
                  <ul className="mb-0">
                    {offboardFailures.map((r) => (
                      <li key={r.allocation_id}>{r.product || 'Allocation'} ({r.reference || r.allocation_id}): {r.error}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="text-muted small mb-0">Request a fresh preview before running offboarding again.</p>
            </div>
          )}
        </div>
      </div>

      {/* Release modal */}
      {releaseTarget && (
        <Modal title={`Release allocation ${releaseTarget.allocation_reference || `#${releaseTarget.id}`}`} onClose={closeRelease}>
          <p style={{ marginTop: 0 }}>
            This releases the seat on agreement <strong>{releaseTarget.agreement_number || '—'}</strong>
            {releaseTarget.product_name ? ` (${releaseTarget.product_name})` : ''}, returns the seat to the
            agreement&apos;s available entitlement, marks the allocation <strong>Revoked</strong>, and notifies
            the assigned employee. The change is audited and cannot be undone.
          </p>
          <Field label="Release reason (optional)" hint="Recorded on the allocation and in its history." error={releaseError}>
            <textarea className="input" rows={3} value={releaseReason}
              onChange={(e) => setReleaseReason(e.target.value)} disabled={releaseBusy} />
          </Field>
          <div className="row-end" style={{ marginTop: 12 }}>
            <button type="button" className="btn-ghost" onClick={closeRelease} disabled={releaseBusy}>Cancel</button>
            <button type="button" className="btn-danger" onClick={submitRelease} disabled={releaseBusy}>
              {releaseBusy ? 'Releasing…' : 'Confirm release'}
            </button>
          </div>
        </Modal>
      )}

      {/* History modal */}
      {historyTarget && (
        <Modal title={`Allocation history ${historyTarget.allocation_reference || `#${historyTarget.id}`}`} onClose={closeHistory} size="lg">
          <HistoryList
            items={historyItems}
            loading={historyLoading}
            error={historyError}
            emptyText="No history recorded for this allocation."
          />
        </Modal>
      )}

      {/* Offboarding confirm */}
      {confirmOffboard && (
        <ConfirmDialog
          title="Confirm employee offboarding"
          message={`Revoke ${previewCount} active or reserved allocation(s) for the selected employee? Their seats are returned to each agreement, they are notified, and the action is audited. This cannot be undone.`}
          confirmLabel="Revoke seats"
          danger
          busy={offboardBusy}
          onConfirm={executeOffboard}
          onCancel={() => { if (!offboardBusy) setConfirmOffboard(false); }}
        />
      )}
    </div>
  );
}
export { LicenseAllocationsPage };
export default LicenseAllocationsPage;
