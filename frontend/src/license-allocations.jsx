import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { Badge, Field, EmptyState, DataTable, Pager, PageHeader, Modal, ConfirmDialog, UserSelect } from './components';
import { fetchPage } from './api-utils';
import { parseApiError } from './api-utils';
import api from './api';
import { licensingCapabilities, buildAllocationListUrl, ALLOCATION_TYPE_LABELS, ALLOCATION_STATUS_LABELS, allocationStatusBadgeVariant } from './licensing-utils';

function LicenseAllocationsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [f, setF] = useState({ search: '', status: '', allocation_type: '', agreement: '' });

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
  const [offboardPreview, setOffboardPreview] = useState(null);
  const [offboardPreviewLoading, setOffboardPreviewLoading] = useState(false);
  const [offboardPreviewError, setOffboardPreviewError] = useState('');
  const [offboardBusy, setOffboardBusy] = useState(false);
  const [offboardError, setOffboardError] = useState('');
  const [offboardResult, setOffboardResult] = useState(null);
  const [confirmOffboard, setConfirmOffboard] = useState(false);

  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); } catch { setError('Could not load allocations.'); }
    finally { setLoading(false); }
  };
  const builtUrl = useMemo(() => buildAllocationListUrl(f, null, page), [f, page]);
  useEffect(() => { const t = setTimeout(() => loadUrl(builtUrl), 250); return () => clearTimeout(t); }, [builtUrl]);

  const doAction = async (id, action, body = {}) => {
    try { await api.post(`/licensing/allocations/${id}/${action}/`, body); setMessage('Action completed.'); loadUrl(builtUrl); } catch (e) { setError(parseApiError(e).global || 'Action failed.'); }
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
      setMessage('Allocation released.');
      setReleaseTarget(null);
      setReleaseReason('');
      await loadUrl(builtUrl);
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
      setHistoryItems(Array.isArray(r.data) ? r.data : (r.data.results || []));
    } catch (e) {
      setHistoryError(parseApiError(e).global || 'Could not load history.');
    } finally {
      setHistoryLoading(false);
    }
  };
  const closeHistory = () => { setHistoryTarget(null); setHistoryItems([]); setHistoryError(''); };

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
      setOffboardPreviewError(parseApiError(e).global || 'Preview failed.');
    } finally {
      setOffboardPreviewLoading(false);
    }
  };

  const executeOffboard = async () => {
    if (offboardBusy) return;
    setOffboardBusy(true);
    setOffboardError('');
    try {
      const r = await api.post('/licensing/allocations/offboard/', { user_id: offboardUserId, reason: `Employee offboarding for user ${offboardUserId}` });
      setOffboardResult(r.data);
      setConfirmOffboard(false);
      setMessage('Offboarding completed.');
      await loadUrl(builtUrl);
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
    { key: 'actions', label: 'Actions', render: (v) => (
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {v.status !== 'active' && <button className="btn btn-sm btn-outline" onClick={() => doAction(v.id, 'activate')}>Activate</button>}
        <button className="btn btn-sm btn-outline" onClick={() => doAction(v.id, 'verify')}>Verify</button>
        {v.status !== 'revoked' && <button className="btn btn-sm btn-outline" onClick={() => openRelease(v)}>Release</button>}
        <button className="btn btn-sm btn-outline" onClick={() => openHistory(v)}>History</button>
        <button className="btn btn-sm btn-outline danger" onClick={() => { const r = window.prompt('Revocation reason:'); if (r) doAction(v.id, 'revoke', { reason: r }); }}>Revoke</button>
      </div>
    ) },
  ];
  if (!caps.canManageAllocations) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-allocations-page">
      <PageHeader title="License Allocations" />
      {message && <div className="alert alert-success">{message}</div>}
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Search" required={false}><input className="input" value={f.search} onChange={(e) => setF({ ...f, search: e.target.value })} /></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(ALLOCATION_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Type" required={false}><select className="input" value={f.allocation_type} onChange={(e) => setF({ ...f, allocation_type: e.target.value })}><option value="">All</option>{Object.entries(ALLOCATION_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      <DataTable columns={columns} rows={items} keyOf="id" loading={loading} emptyTitle="No allocations found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}

      {/* Offboarding workflow */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-body">
          <h5>Employee Offboarding Preview</h5>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <UserSelect value={offboardUserId} onChange={setOffboardUserId} label="Employee" />
            <button className="btn btn-outline" onClick={requestOffboardPreview} disabled={offboardPreviewLoading || !offboardUserId}>
              {offboardPreviewLoading ? 'Loading…' : 'Preview'}
            </button>
          </div>
          {offboardPreviewError && <div className="alert alert-danger" style={{ marginTop: 8 }}>{offboardPreviewError}</div>}
          {offboardPreview && (
            <div style={{ marginTop: 12 }}>
              <p>Affected allocations: {offboardPreview.count}</p>
              {(offboardPreview.allocations || []).length === 0 ? <p className="text-muted">No active allocations.</p> : (
                <table className="table table-sm">
                  <thead><tr><th>Product</th><th>Agreement</th><th>Reference</th><th>Status</th></tr></thead>
                  <tbody>
                    {offboardPreview.allocations.map((a) => (
                      <tr key={a.id}><td>{a.product_name}</td><td>{a.agreement_number}</td><td>{a.allocation_reference}</td><td>{a.status}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              {(offboardPreview.allocations || []).length > 0 && (
                <button className="btn btn-danger" style={{ marginTop: 8 }} onClick={() => setConfirmOffboard(true)} disabled={offboardBusy}>
                  {offboardBusy ? 'Working…' : 'Execute Offboarding'}
                </button>
              )}
            </div>
          )}
          {offboardError && <div className="alert alert-danger" style={{ marginTop: 8 }}>{offboardError}</div>}
          {offboardResult && (
            <div className="alert alert-success" style={{ marginTop: 8 }}>
              Revoked {offboardResult.revoked_count} of {offboardResult.total_active} allocations.
            </div>
          )}
        </div>
      </div>

      {/* Release modal */}
      {releaseTarget && (
        <Modal title={`Release Allocation ${releaseTarget.allocation_reference || releaseTarget.id}`} onClose={closeRelease}>
          <Field label="Release reason" error={releaseError}>
            <textarea className="input" rows={3} value={releaseReason} onChange={(e) => setReleaseReason(e.target.value)} />
          </Field>
          {releaseError && <div className="alert alert-danger">{releaseError}</div>}
          <div className="row-end" style={{ marginTop: 12 }}>
            <button type="button" className="btn-ghost" onClick={closeRelease} disabled={releaseBusy}>Cancel</button>
            <button type="button" className="btn-primary" onClick={submitRelease} disabled={releaseBusy}>
              {releaseBusy ? 'Working…' : 'Release'}
            </button>
          </div>
        </Modal>
      )}

      {/* History modal */}
      {historyTarget && (
        <Modal title={`Allocation History ${historyTarget.allocation_reference || historyTarget.id}`} onClose={closeHistory}>
          {historyLoading && <div>Loading…</div>}
          {historyError && <div className="alert alert-danger">{historyError}</div>}
          {!historyLoading && !historyError && historyItems.length === 0 && <div className="text-muted">No history.</div>}
          {!historyLoading && historyItems.length > 0 && (
            <table className="table table-sm">
              <thead><tr><th>Time</th><th>Event</th><th>Previous</th><th>New</th><th>Actor</th><th>Detail</th></tr></thead>
              <tbody>
                {historyItems.map((h) => (
                  <tr key={h.id}>
                    <td>{h.created_at}</td>
                    <td>{h.event_type}</td>
                    <td>{h.previous_status}</td>
                    <td>{h.new_status}</td>
                    <td>{h.actor_email || h.actor}</td>
                    <td>{h.detail ? JSON.stringify(h.detail) : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Modal>
      )}

      {/* Offboarding confirm */}
      {confirmOffboard && (
        <ConfirmDialog
          title="Confirm Offboarding"
          message={`Release/revoke ${offboardPreview?.count || 0} allocation(s) for user ${offboardUserId}?`}
          confirmLabel="Execute"
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
