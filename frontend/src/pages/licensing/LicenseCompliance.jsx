import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../auth';
import { AccessDenied, Badge, Field, DataTable, Pager, PageHeader, Modal, ConfirmDialog } from '../../components';
import { fetchPage, parseApiError } from '../../api-utils';
import api from '../../api';
import {
  licensingCapabilities,
  buildFindingListUrl,
  FINDING_TYPE_LABELS,
  FINDING_SEVERITY_LABELS,
  FINDING_STATUS_LABELS,
} from '../../shared/licensing-utils';

const CLOSED_STATUSES = ['resolved', 'false_positive'];

function LicenseCompliancePage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page] = useState(1); // pager loads absolute next/previous URLs
  const [lastUrl, setLastUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [f, setF] = useState({ search: '', finding_type: '', severity: '', status: '' });
  const [busyId, setBusyId] = useState(null);

  // Remediation state
  const [remediateTarget, setRemediateTarget] = useState(null);
  const [remediateNote, setRemediateNote] = useState('');
  const [remediateReevaluate, setRemediateReevaluate] = useState(false);
  const [remediateBusy, setRemediateBusy] = useState(false);
  const [remediateError, setRemediateError] = useState('');

  // Resolve / false-positive state
  const [resolveTarget, setResolveTarget] = useState(null);
  const [resolveNote, setResolveNote] = useState('');
  const [resolveBusy, setResolveBusy] = useState(false);
  const [resolveError, setResolveError] = useState('');

  const builtUrl = useMemo(() => buildFindingListUrl(f, null, page), [f, page]);

  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous);
      setLastUrl(url);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load findings.');
    } finally { setLoading(false); }
  };
  const reload = () => loadUrl(lastUrl || builtUrl);

  useEffect(() => {
    if (!caps.canViewCompliance) return undefined;
    const t = setTimeout(() => loadUrl(builtUrl), 250);
    return () => clearTimeout(t);
  }, [builtUrl, caps.canViewCompliance]);

  const doAcknowledge = async (row) => {
    if (busyId) return;
    setBusyId(row.id); setError(''); setMessage('');
    try {
      await api.post(`/licensing/findings/${row.id}/acknowledge/`);
      setMessage(`Finding ${row.id} acknowledged.`);
      await reload();
    } catch (e) {
      setError(parseApiError(e).global || 'Could not acknowledge the finding.');
    } finally { setBusyId(null); }
  };

  const openRemediate = (row) => {
    setRemediateTarget(row);
    setRemediateNote('');
    setRemediateReevaluate(false);
    setRemediateError('');
  };
  const closeRemediate = () => {
    if (!remediateBusy) { setRemediateTarget(null); setRemediateNote(''); setRemediateError(''); }
  };
  const submitRemediate = async () => {
    if (!remediateTarget || remediateBusy) return;
    const note = remediateNote.trim();
    if (!note) { setRemediateError('A remediation note is required.'); return; }
    setRemediateBusy(true); setRemediateError('');
    try {
      const r = await api.post(`/licensing/findings/${remediateTarget.id}/remediate/`, {
        remediation_note: note,
        reevaluate: remediateReevaluate,
      });
      const status = r?.data?.status;
      setMessage(status === 'resolved'
        ? 'Remediation recorded and compliance re-evaluated: the finding is now resolved.'
        : `Remediation recorded. Finding status: ${FINDING_STATUS_LABELS[status] || status || 'Acknowledged'}.`);
      setRemediateTarget(null);
      setRemediateNote('');
      await reload();
    } catch (e) {
      setRemediateError(parseApiError(e).global || 'Remediation failed.');
    } finally {
      setRemediateBusy(false);
    }
  };

  const openResolve = (row, falsePositive) => {
    setResolveTarget({ row, falsePositive });
    setResolveNote('');
    setResolveError('');
  };
  const closeResolve = () => {
    if (!resolveBusy) { setResolveTarget(null); setResolveNote(''); setResolveError(''); }
  };
  const submitResolve = async () => {
    if (!resolveTarget || resolveBusy) return;
    const note = resolveNote.trim();
    if (!note) { setResolveError('A resolution note is required.'); return; }
    const action = resolveTarget.falsePositive ? 'false-positive' : 'resolve';
    setResolveBusy(true); setResolveError('');
    try {
      await api.post(`/licensing/findings/${resolveTarget.row.id}/${action}/`, { resolution_note: note });
      setMessage(resolveTarget.falsePositive
        ? `Finding ${resolveTarget.row.id} marked as a false positive.`
        : `Finding ${resolveTarget.row.id} resolved.`);
      setResolveTarget(null);
      setResolveNote('');
      await reload();
    } catch (e) {
      setResolveError(parseApiError(e).global || 'Could not update the finding.');
    } finally {
      setResolveBusy(false);
    }
  };

  // Backend LicenseCompliancePermission allows IT Support to view/acknowledge,
  // while resolve/false-positive/remediation require IT Manager or admin.
  if (!caps.canViewCompliance) return <AccessDenied />;

  const canManage = caps.canManageCompliance;

  const columns = [
    { key: 'title', label: 'Title' },
    { key: 'finding_type', label: 'Type', render: (v) => FINDING_TYPE_LABELS[v.finding_type] || v.finding_type },
    { key: 'severity', label: 'Severity', render: (v) => <Badge kind="status" value={FINDING_SEVERITY_LABELS[v.severity] || v.severity} /> },
    { key: 'product_name', label: 'Product' },
    { key: 'agreement_number', label: 'Agreement', render: (v) => (v.agreement_number ? <a href={`#/licenses/${v.agreement}`}>{v.agreement_number}</a> : '—') },
    { key: 'user_email', label: 'User' },
    { key: 'asset_tag', label: 'Asset' },
    { key: 'status', label: 'Status', render: (v) => FINDING_STATUS_LABELS[v.status] || v.status },
    { key: 'detected_at', label: 'Detected' },
    { key: 'resolved_at', label: 'Resolved At' },
    { key: 'actions', label: 'Actions', render: (v) => {
      if (CLOSED_STATUSES.includes(v.status)) return <span className="text-muted">Closed</span>;
      const rowBusy = busyId === v.id;
      return (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <button className="btn-small btn-secondary" onClick={() => doAcknowledge(v)} disabled={rowBusy}>
            Acknowledge
          </button>
          {canManage && (
            <>
              <button className="btn-small btn-secondary" onClick={() => openRemediate(v)} disabled={rowBusy}>Remediate</button>
              <button className="btn-small btn-secondary" onClick={() => openResolve(v, false)} disabled={rowBusy}>Resolve</button>
              <button className="btn-small btn-secondary" onClick={() => openResolve(v, true)} disabled={rowBusy}>False Positive</button>
            </>
          )}
        </div>
      );
    } },
  ];

  return (
    <div className="license-compliance-page">
      <PageHeader title="License Compliance Findings" />
      {!canManage && (
        <p className="text-muted small">
          You can acknowledge findings. Recording remediation or resolving findings requires
          IT Manager or System Admin permission.
        </p>
      )}
      {message && <div className="alert alert-success" role="status">{message}</div>}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Type" required={false}><select className="input" value={f.finding_type} onChange={(e) => setF({ ...f, finding_type: e.target.value })}><option value="">All</option>{Object.entries(FINDING_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Severity" required={false}><select className="input" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}><option value="">All</option>{Object.entries(FINDING_SEVERITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(FINDING_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      {loading
        ? <p className="muted" role="status">Loading findings…</p>
        : <DataTable columns={columns} rows={items} keyOf={(r) => r.id} emptyTitle="No findings found" />}
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}

      {remediateTarget && (
        <Modal title={`Remediate Finding ${remediateTarget.id}`} onClose={closeRemediate}>
          <p style={{ marginTop: 0 }}>{remediateTarget.title}</p>
          {remediateTarget.description && <p className="text-muted">{remediateTarget.description}</p>}
          <p className="text-muted small">
            Recording remediation acknowledges the finding. It is only resolved when the
            underlying condition is gone and compliance is re-evaluated.
          </p>
          <Field label="Remediation notes" required error={remediateError}>
            <textarea className="input" rows={4} value={remediateNote}
              onChange={(e) => setRemediateNote(e.target.value)} disabled={remediateBusy} />
          </Field>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8 }}>
            <input type="checkbox" checked={remediateReevaluate}
              onChange={(e) => setRemediateReevaluate(e.target.checked)} disabled={remediateBusy} />
            Re-evaluate compliance after remediation (resolves only if the condition is actually gone)
          </label>
          <div className="row-end" style={{ marginTop: 12 }}>
            <button type="button" className="btn-ghost" onClick={closeRemediate} disabled={remediateBusy}>Cancel</button>
            <button type="button" className="btn-primary" onClick={submitRemediate} disabled={remediateBusy}>
              {remediateBusy ? 'Saving…' : 'Record Remediation'}
            </button>
          </div>
        </Modal>
      )}

      {resolveTarget && (
        <ConfirmDialog
          title={resolveTarget.falsePositive ? `Mark Finding ${resolveTarget.row.id} as false positive` : `Resolve Finding ${resolveTarget.row.id}`}
          message={resolveTarget.row.title}
          confirmLabel={resolveTarget.falsePositive ? 'Mark false positive' : 'Resolve finding'}
          danger={!resolveTarget.falsePositive}
          busy={resolveBusy}
          onConfirm={submitResolve}
          onCancel={closeResolve}
        >
          <Field
            label={resolveTarget.falsePositive ? 'Justification' : 'Resolution note'}
            required
            error={resolveError}
            hint={resolveTarget.falsePositive
              ? 'Explains why the finding is not a real compliance issue; kept on the finding.'
              : 'Describes how the finding was resolved; kept on the finding.'}
          >
            <textarea className="input" rows={3} value={resolveNote}
              onChange={(e) => setResolveNote(e.target.value)} disabled={resolveBusy} />
          </Field>
        </ConfirmDialog>
      )}
    </div>
  );
}
export { LicenseCompliancePage };
export default LicenseCompliancePage;

