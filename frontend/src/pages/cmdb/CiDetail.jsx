import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Badge, ConfirmDialog, DataTable, EmptyState, Field, LoadingRows, PageHeader,
} from '../../components';
import { parseApiError } from '../../api-utils';
import {
  CI_LIFECYCLE_LABELS,
  CI_STATUS_LABELS,
  CRITICALITY_LABELS,
  DATA_CLASSIFICATION_LABELS,
  DRIFT_SEVERITY_LABELS,
  DRIFT_STATUS_LABELS,
  ENVIRONMENT_LABELS,
  MONITORING_STATE_LABELS,
  RELATIONSHIP_CONFIDENCE_LABELS,
  RELATIONSHIP_STATUS_LABELS,
  RELATIONSHIP_TYPE_LABELS,
  SOURCE_LABELS,
  VALIDATED_SYSTEM_IMPACT_LABELS,
  formatDateTime,
  safeResults,
} from '../../shared/cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS } from '../../shared/cmdb';

function labelOf(map, value) {
  if (value == null || value === '') return '—';
  return map[value] || String(value).replace(/_/g, ' ');
}

function DetailRow({ label, value }) {
  return (
    <div className="detail-row" style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: 8, padding: '6px 0' }}>
      <div className="muted">{label}</div>
      <div>{value ?? '—'}</div>
    </div>
  );
}

export function CiDetail({ id: idProp, match }) {
  const id = Number(idProp ?? match?.params?.id);
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [ci, setCi] = useState(null);
  const [relationships, setRelationships] = useState([]);
  const [history, setHistory] = useState([]);
  const [drift, setDrift] = useState([]);
  const [baselines, setBaselines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [busy, setBusy] = useState('');
  const [verifyNote, setVerifyNote] = useState('');
  const [retireReason, setRetireReason] = useState('');
  const [retireImpact, setRetireImpact] = useState(null);
  const [showRetire, setShowRetire] = useState(false);
  const [showVerify, setShowVerify] = useState(false);
  const [baselineCompare, setBaselineCompare] = useState(null);
  const [baselineCompareError, setBaselineCompareError] = useState('');
  const [baselineCompareBusy, setBaselineCompareBusy] = useState(false);

  const canView = CMDB_PERMISSIONS.canViewCIDetail(role);
  const canEdit = CMDB_PERMISSIONS.canEditCI(role);
  const canVerify = CMDB_PERMISSIONS.canVerifyCI(role) || CMDB_PERMISSIONS.canVerifyCIAction?.(role);
  const canRetire = CMDB_PERMISSIONS.canRetireCI(role) || CMDB_PERMISSIONS.canRetireCIAction?.(role);

  const load = async () => {
    if (!id) return;
    setLoading(true);
    setError('');
    try {
      const [ciRes, relRes, histRes, driftRes, baseRes] = await Promise.allSettled([
        api.get(CMDB_API_CONTRACT.ciDetail.endpoint(id)),
        api.get(`/cmdb/items/${id}/relationships/`),
        api.get(`/cmdb/items/${id}/history/`),
        api.get(`/cmdb/drift/?ci=${id}`),
        api.get('/cmdb/baselines/'),
      ]);
      if (ciRes.status === 'fulfilled') setCi(ciRes.value.data);
      else throw ciRes.reason;
      setRelationships(relRes.status === 'fulfilled' ? safeResults(relRes.value.data?.results ?? relRes.value.data) : []);
      setHistory(histRes.status === 'fulfilled' ? safeResults(histRes.value.data?.results ?? histRes.value.data) : safeResults(ciRes.value.data?.history));
      setDrift(driftRes.status === 'fulfilled' ? safeResults(driftRes.value.data?.results ?? driftRes.value.data) : []);
      setBaselines(baseRes.status === 'fulfilled' ? safeResults(baseRes.value.data?.results ?? baseRes.value.data) : []);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load configuration item details.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const relatedId = (r) => (String(r.source_ci) === String(id) ? r.target_ci : r.source_ci);
  const relatedNumber = (r) => (String(r.source_ci) === String(id) ? r.target_ci_number : r.source_ci_number);

  const doVerify = async () => {
    if (!ci) return;
    setBusy('verify');
    setActionError('');
    setActionMsg('');
    try {
      await api.post(`/cmdb/items/${id}/verify/`, {
        verification_note: verifyNote || '',
        expected_record_version: ci.record_version ?? null,
      });
      setActionMsg('Configuration item verified.');
      setShowVerify(false);
      setVerifyNote('');
      await load();
    } catch (e) {
      setActionError(parseApiError(e).global || 'Could not verify configuration item.');
    } finally {
      setBusy('');
    }
  };

  const doRetire = async (acknowledge = false) => {
    if (!ci || !retireReason.trim()) return;
    setBusy('retire');
    setActionError('');
    setActionMsg('');
    try {
      await api.post(`/cmdb/items/${id}/retire/`, {
        reason: retireReason.trim(),
        expected_record_version: ci.record_version ?? null,
        acknowledge_impact: acknowledge,
      });
      setActionMsg('Configuration item retired.');
      setShowRetire(false);
      setRetireReason('');
      setRetireImpact(null);
      await load();
    } catch (e) {
      const status = e?.response?.status;
      const data = e?.response?.data || {};
      if (status === 409 && data.impact) {
        setRetireImpact(data.impact);
        setActionError('Retiring this CI affects other records. Review the impact summary and acknowledge it to continue.');
      } else {
        setActionError(parseApiError(e).global || data.detail || 'Could not retire configuration item.');
      }
    } finally {
      setBusy('');
    }
  };

  const compareToBaseline = async () => {
    setBaselineCompareBusy(true);
    setBaselineCompareError('');
    setBaselineCompare(null);
    try {
      const res = await api.get(`/cmdb/items/${id}/compare-baseline/`);
      setBaselineCompare(res.data || null);
    } catch (e) {
      setBaselineCompareError(parseApiError(e).global || e?.response?.data?.detail || 'Could not compare CI to baseline.');
    } finally {
      setBaselineCompareBusy(false);
    }
  };

  if (role === 'employee' || !canView) {
    return <div className="error-summary" role="alert">You do not have permission to view this configuration item.</div>;
  }
  if (loading) return <div className="panel panel-pad"><LoadingRows n={10} /></div>;
  if (error) return <div className="error-summary" role="alert">{error}</div>;
  if (!ci) return <EmptyState title="Configuration item not found" hint="The requested CI may have been removed or you may not have access." />;

  const isRetired = ['retired', 'disposed'].includes(ci.status);

  return (
    <div>
      <PageHeader
        title={ci.ci_number || `CI #${ci.id}`}
        sub={`${ci.name || 'Unnamed CI'} · ${labelOf(CI_STATUS_LABELS, ci.status)} · ${labelOf(CRITICALITY_LABELS, ci.criticality)}`}
        actions={(
          <>
            <a className="btn-small" href="#/cmdb/items">Back to CIs</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/relationships`}>Relationships</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/dependencies`}>Dependencies</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/impact`}>Impact</a>
            {canEdit && <a className="btn-small" href={`#/cmdb/items/${id}/edit`}>Edit</a>}
            {canVerify && !isRetired && <button type="button" className="btn-small" onClick={() => setShowVerify(true)}>Verify</button>}
            {canRetire && !isRetired && <button type="button" className="btn-danger" onClick={() => setShowRetire(true)}>Retire</button>}
          </>
        )}
      />

      {actionMsg && <div className="alert alert-success" role="status">{actionMsg}</div>}
      {actionError && <div className="error-summary" role="alert">{actionError}</div>}

      <div className="split-grid split-2" style={{ alignItems: 'start' }}>
        <div className="panel panel-pad">
          <h3>Overview</h3>
          <DetailRow label="CI Number" value={ci.ci_number || '—'} />
          <DetailRow label="Name" value={ci.name || '—'} />
          <DetailRow label="Type" value={ci.ci_type_name || ci.ci_type || '—'} />
          <DetailRow label="Status" value={<Badge kind="status" value={ci.status} label={labelOf(CI_STATUS_LABELS, ci.status)} />} />
          <DetailRow label="Lifecycle" value={labelOf(CI_LIFECYCLE_LABELS, ci.lifecycle_state)} />
          <DetailRow label="Criticality" value={<Badge kind="priority" value={ci.criticality} label={labelOf(CRITICALITY_LABELS, ci.criticality)} />} />
          <DetailRow label="Environment" value={labelOf(ENVIRONMENT_LABELS, ci.environment)} />
          <DetailRow label="Source" value={labelOf(SOURCE_LABELS, ci.source)} />
          <DetailRow label="Monitoring" value={labelOf(MONITORING_STATE_LABELS, ci.monitoring_state)} />
          <DetailRow label="Data Classification" value={labelOf(DATA_CLASSIFICATION_LABELS, ci.data_classification)} />
          <DetailRow label="Validated Impact" value={labelOf(VALIDATED_SYSTEM_IMPACT_LABELS, ci.validated_system_impact)} />
          <DetailRow label="Record Version" value={ci.record_version ?? '—'} />
          <DetailRow label="Last Verified" value={ci.last_verified_at ? formatDateTime(ci.last_verified_at) : 'Never'} />
          <DetailRow label="Updated" value={ci.updated_at ? formatDateTime(ci.updated_at) : '—'} />
        </div>

        <div className="panel panel-pad">
          <h3>Ownership and links</h3>
          <DetailRow label="Owner" value={ci.owner_username || (ci.owner ? `User #${ci.owner}` : '—')} />
          <DetailRow label="Technical Owner" value={ci.technical_owner ? `User #${ci.technical_owner}` : '—'} />
          <DetailRow label="Department" value={ci.department_name || (ci.department ? `Department #${ci.department}` : '—')} />
          <DetailRow label="Location" value={ci.location || '—'} />
          <DetailRow label="Asset" value={ci.asset_tag ? `${ci.asset_tag}${ci.asset ? ` (#${ci.asset})` : ''}` : (ci.asset ? `Asset #${ci.asset}` : '—')} />
          <DetailRow label="Software Product" value={ci.software_product ? `Software #${ci.software_product}` : '—'} />
          <DetailRow label="Service" value={ci.service_name || (ci.service ? `Service #${ci.service}` : '—')} />
          <DetailRow label="Vendor" value={ci.vendor ? `Vendor #${ci.vendor}` : '—'} />
          <DetailRow label="Manufacturer" value={ci.manufacturer || '—'} />
          <DetailRow label="Model" value={ci.model || '—'} />
          <DetailRow label="Serial Number" value={ci.serial_number || '—'} />
          <DetailRow label="Hostname" value={ci.hostname || '—'} />
          <DetailRow label="IP Address" value={ci.ip_address || '—'} />
          <DetailRow label="DNS Name" value={ci.dns_name || '—'} />
          <DetailRow label="External Reference" value={ci.external_reference || '—'} />
        </div>
      </div>

      {ci.description ? (
        <div className="panel panel-pad" style={{ marginTop: 16 }}>
          <h3>Description</h3>
          <p style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{ci.description}</p>
        </div>
      ) : null}

      <div className="panel panel-pad" style={{ marginTop: 16 }}>
        <h3>Attributes</h3>
        {ci.attributes && Object.keys(ci.attributes).length ? (
          <DataTable
            columns={[
              { key: 'key', label: 'Attribute' },
              { key: 'value', label: 'Value', render: (r) => (typeof r.value === 'object' ? JSON.stringify(r.value) : String(r.value ?? '—')) },
            ]}
            rows={Object.entries(ci.attributes).map(([key, value]) => ({ key, value }))}
            keyOf={(r) => r.key}
            emptyTitle="No attributes"
          />
        ) : (
          <EmptyState title="No attributes recorded" hint="Schema-defined or custom attributes will appear here when present." />
        )}
      </div>

      <div className="split-grid split-2" style={{ marginTop: 16, alignItems: 'start' }}>
        <div className="panel panel-pad">
          <div className="panel-head"><h3>Relationships</h3><a className="link-small" href={`#/cmdb/items/${id}/relationships`}>Manage</a></div>
          {relationships.length === 0 ? (
            <EmptyState title="No relationships" hint="Create relationships to model dependencies and service impact." action={<a className="btn-small" href={`#/cmdb/items/${id}/relationships`}>Add relationship</a>} />
          ) : (
            <DataTable
              columns={[
                { key: 'direction', label: 'Direction', render: (r) => (String(r.source_ci) === String(id) ? 'Outgoing' : 'Incoming') },
                { key: 'relationship_type', label: 'Type', render: (r) => labelOf(RELATIONSHIP_TYPE_LABELS, r.relationship_type) },
                { key: 'related', label: 'Related CI', render: (r) => <a href={`#/cmdb/items/${relatedId(r)}`}>{relatedNumber(r) || `CI #${relatedId(r)}`}</a> },
                { key: 'status', label: 'Status', render: (r) => labelOf(RELATIONSHIP_STATUS_LABELS, r.status) },
                { key: 'confidence', label: 'Confidence', render: (r) => labelOf(RELATIONSHIP_CONFIDENCE_LABELS, r.confidence) },
              ]}
              rows={relationships}
              keyOf={(r) => r.id}
              emptyTitle="No relationships"
            />
          )}
        </div>

        <div className="panel panel-pad">
          <div className="panel-head"><h3>Drift findings for this CI</h3><a className="link-small" href="#/cmdb/drift">View drift workspace</a></div>
          {drift.length === 0 ? (
            <EmptyState title="No drift findings for this CI" hint="Drift findings appear when approved baselines differ from the current configuration." />
          ) : (
            <DataTable
              columns={[
                { key: 'severity', label: 'Severity', render: (r) => labelOf(DRIFT_SEVERITY_LABELS, r.severity) },
                { key: 'status', label: 'Status', render: (r) => labelOf(DRIFT_STATUS_LABELS, r.status) },
                { key: 'finding_type', label: 'Type', render: (r) => String(r.finding_type || '—').replace(/_/g, ' ') },
                { key: 'field_name', label: 'Field', render: (r) => r.field_name || '—' },
                { key: 'expected', label: 'Expected', render: (r) => (r.expected_value == null || r.expected_value === '' ? '—' : String(r.expected_value)) },
                { key: 'actual', label: 'Current', render: (r) => (r.actual_value == null || r.actual_value === '' ? '—' : String(r.actual_value)) },
                { key: 'detected_at', label: 'Detected', render: (r) => r.detected_at ? formatDateTime(r.detected_at) : '—' },
                { key: 'actions', label: 'Actions', render: () => <a className="btn-small" href="#/cmdb/drift">Manage in Drift</a> },
              ]}
              rows={drift.slice(0, 10)}
              keyOf={(r) => r.id}
              emptyTitle="No drift findings"
            />
          )}
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 16 }}>
        <div className="panel-head"><h3>History and audit</h3><span className="muted">Read-only immutable event trail</span></div>
        {history.length === 0 ? (
          <EmptyState title="No history recorded" hint="Changes, verification, and lifecycle actions will appear here." />
        ) : (
          <DataTable
            columns={[
              { key: 'created_at', label: 'When', render: (r) => formatDateTime(r.created_at) },
              { key: 'event_type', label: 'Event', render: (r) => String(r.event_type || '—').replace(/_/g, ' ') },
              { key: 'actor', label: 'Actor', render: (r) => r.actor_username || r.actor_email || (r.actor ? `User #${r.actor}` : 'System') },
              { key: 'source', label: 'Source', render: (r) => r.source || '—' },
              { key: 'status', label: 'Status change', render: (r) => (r.previous_status || r.new_status) ? `${r.previous_status || '—'} -> ${r.new_status || '—'}` : '—' },
              { key: 'detail', label: 'Details', render: (r) => r.detail || (r.changed_fields && Object.keys(r.changed_fields).length ? `Changed: ${Object.keys(r.changed_fields).join(', ')}` : '—') },
            ]}
            rows={history}
            keyOf={(r, i) => r.id ?? `${r.created_at}-${i}`}
            emptyTitle="No history recorded"
          />
        )}
      </div>

      <div className="panel panel-pad" style={{ marginTop: 16 }}>
        <div className="panel-head"><h3>Baselines and comparison</h3><a className="link-small" href="#/cmdb/baselines">Manage baselines</a></div>
        <div className="table-actions" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
          <button type="button" className="btn-small" onClick={compareToBaseline} disabled={baselineCompareBusy}>
            {baselineCompareBusy ? 'Comparing…' : 'Compare to latest approved baseline'}
          </button>
          <span className="muted">Per-CI shortcut using backend comparison endpoint (latest approved baseline when available).</span>
        </div>
        {baselineCompareError && <div className="error-summary" role="alert">{baselineCompareError}</div>}
        {baselineCompare && (
          <div style={{ marginBottom: 12 }}>
            <p className="muted">Baseline: {baselineCompare.baseline_code || baselineCompare.baseline_id || '—'} · Drift detected: {baselineCompare.drift ? 'Yes' : 'No'} · Differences: {(baselineCompare.diffs || []).length}</p>
            {(baselineCompare.diffs || []).length === 0 ? (
              <EmptyState title="No differences found." hint="This CI matches the compared baseline for checked fields." />
            ) : (
              <DataTable
                columns={[
                  { key: 'field_name', label: 'Field', render: (r) => r.field_name || r.field || '—' },
                  { key: 'expected', label: 'Expected (baseline)', render: (r) => (r.expected_value == null || r.expected_value === '' ? '—' : String(r.expected_value)) },
                  { key: 'actual', label: 'Current', render: (r) => (r.actual_value == null || r.actual_value === '' ? String(r.current_value ?? '—') : String(r.actual_value)) },
                ]}
                rows={baselineCompare.diffs || []}
                keyOf={(r, i) => `${r.field_name || i}-${i}`}
                emptyTitle="No differences."
              />
            )}
          </div>
        )}
        {baselines.length === 0 ? (
          <EmptyState title="No baselines available" hint="Create and approve a baseline to compare this CI against an expected state." />
        ) : (
          <p className="muted" style={{ marginBottom: 0 }}>
            {baselines.length} baseline{baselines.length === 1 ? '' : 's'} exist in the CMDB. Use the Baselines screen for full review, approval, superseding, and multi-CI comparison workflows.
          </p>
        )}
      </div>

      {showVerify && (
        <ConfirmDialog
          title="Verify configuration item"
          message={`Mark ${ci.ci_number || ci.name} as verified. You can optionally add a verification note.`}
          confirmLabel={busy === 'verify' ? 'Verifying…' : 'Verify CI'}
          busy={busy === 'verify'}
          onCancel={() => { if (!busy) { setShowVerify(false); setVerifyNote(''); } }}
          onConfirm={doVerify}
        >
          <Field label="Verification note">
            <textarea className="input" rows={3} value={verifyNote} onChange={(e) => setVerifyNote(e.target.value)} placeholder="Optional note about what was checked" />
          </Field>
        </ConfirmDialog>
      )}

      {showRetire && (
        <ConfirmDialog
          title="Retire configuration item"
          message="Retiring a CI records a lifecycle change and may affect dependent services or relationships. Provide a reason."
          confirmLabel={busy === 'retire' ? 'Retiring…' : (retireImpact ? 'Acknowledge impact and retire' : 'Retire CI')}
          danger
          busy={busy === 'retire'}
          onCancel={() => { if (!busy) { setShowRetire(false); setRetireReason(''); setRetireImpact(null); } }}
          onConfirm={() => doRetire(!!retireImpact)}
        >
          <Field label="Reason" required>
            <textarea className="input" rows={3} value={retireReason} onChange={(e) => setRetireReason(e.target.value)} placeholder="Why is this CI being retired?" />
          </Field>
          {retireImpact && (
            <div className="panel panel-pad" style={{ marginTop: 12 }}>
              <strong>Impact summary</strong>
              <ul style={{ margin: '8px 0 0 18px' }}>
                {Array.isArray(retireImpact.affected_ci_ids) && <li>Affected CIs: {retireImpact.affected_ci_ids.length}</li>}
                {Array.isArray(retireImpact.affected_services) && <li>Affected services: {retireImpact.affected_services.length}</li>}
                {retireImpact.risk_summary && <li>Risk: {typeof retireImpact.risk_summary === 'object' ? JSON.stringify(retireImpact.risk_summary) : String(retireImpact.risk_summary)}</li>}
              </ul>
            </div>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}


