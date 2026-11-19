import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { DataTable, EmptyState, Field, LoadingRows, PageHeader, Select } from './components';
import { CI_STATUS_LABELS, CRITICALITY_LABELS, safeResults } from './cmdb-utils';

function ciDisplay(row) {
  if (!row) return '—';
  const num = row.ci_number || `CI #${row.id}`;
  return row.name ? `${num} — ${row.name}` : num;
}

export function ImpactAnalysisPage({ id: idProp, match }) {
  const id = Number(idProp ?? match?.params?.id);
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [impact, setImpact] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [depth, setDepth] = useState(3);
  const [includeTickets, setIncludeTickets] = useState(false);
  const [includeChanges, setIncludeChanges] = useState(false);
  const [selectedCiId, setSelectedCiId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!id) return undefined;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({ depth: String(depth) });
    if (includeTickets) params.set('include_tickets', 'true');
    if (includeChanges) params.set('include_changes', 'true');
    api.get(`/cmdb/items/${id}/impact/?${params.toString()}`)
      .then((r) => { if (!cancelled) setImpact(r.data || null); })
      .catch((e) => { if (!cancelled) setError(e?.response?.data?.detail || 'Could not load impact analysis.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, depth, includeTickets, includeChanges]);

  const affectedCIs = useMemo(() => {
    const ids = safeResults(impact?.affected_ci_ids);
    const details = safeResults(impact?.affected_cis);
    if (details.length) return details;
    return ids.map((cid) => ({ id: cid, ci_number: `CI #${cid}`, name: '' }));
  }, [impact]);

  const selectedCi = useMemo(() => affectedCIs.find((c) => Number(c.id) === Number(selectedCiId)) || null, [affectedCIs, selectedCiId]);

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no impact analysis access.</div>;
  }

  const risk = impact?.risk_summary || {};
  const criticalDeps = safeResults(impact?.critical_dependencies);
  const spofs = safeResults(impact?.single_points_of_failure);
  const services = safeResults(impact?.affected_services);
  const departments = safeResults(impact?.affected_departments);
  const owners = safeResults(impact?.affected_owners);
  const tickets = safeResults(impact?.affected_tickets);
  const changes = safeResults(impact?.affected_changes);

  return (
    <div>
      <PageHeader
        title="Impact Analysis"
        sub={`Downstream impact for CI #${id}${impact?.ci_number ? ` (${impact.ci_number})` : ''}`}
        actions={(
          <>
            <a className="btn-small" href={`#/cmdb/items/${id}`}>Back to CI</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/dependencies`}>Dependency Map</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/relationships`}>Relationships</a>
          </>
        )}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="split-grid split-4">
          <Field label="Traversal Depth">
            <Select value={String(depth)} onChange={(e) => setDepth(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((d) => <option key={d} value={String(d)}>{d}</option>)}
            </Select>
          </Field>
          <Field label="Include Tickets">
            <Select value={includeTickets ? 'yes' : 'no'} onChange={(e) => setIncludeTickets(e.target.value === 'yes')}>
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </Select>
          </Field>
          <Field label="Include Changes">
            <Select value={includeChanges ? 'yes' : 'no'} onChange={(e) => setIncludeChanges(e.target.value === 'yes')}>
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </Select>
          </Field>
          <div className="muted" style={{ alignSelf: 'end' }}>
            Affected CIs: {impact?.affected_count ?? affectedCIs.length}{impact?.truncated ? ' (truncated)' : ''}
          </div>
        </div>
        {impact?.warning && <div className="notice" style={{ marginTop: 12 }}>{impact.warning}</div>}
        {impact?.truncated && <div className="notice" style={{ marginTop: 12 }}>Impact results were truncated by backend safety limits. Reduce depth or inspect specific downstream branches.</div>}
      </div>

      {loading ? (
        <div className="panel panel-pad"><LoadingRows n={6} /></div>
      ) : !impact ? (
        <div className="panel panel-pad"><EmptyState title="No impact data." hint="Impact analysis could not be loaded for this CI." /></div>
      ) : (
        <>
          <div className="kpi-grid" style={{ marginBottom: 16 }}>
            <div className="kpi"><div className="kpi-label">Affected CIs</div><div className="kpi-value">{impact.affected_count ?? affectedCIs.length}</div></div>
            <div className="kpi"><div className="kpi-label">Affected Services</div><div className="kpi-value">{services.length}</div></div>
            <div className="kpi"><div className="kpi-label">Critical Dependencies</div><div className="kpi-value">{criticalDeps.length}</div></div>
            <div className="kpi"><div className="kpi-label">Single Points of Failure</div><div className="kpi-value">{spofs.length}</div></div>
          </div>

          <div className="split-grid split-2" style={{ marginBottom: 16 }}>
            <div className="panel panel-pad">
              <h2 style={{ marginTop: 0 }}>Affected Configuration Items</h2>
              {affectedCIs.length === 0 ? (
                <EmptyState title="No downstream CIs affected." hint="No dependent configuration items were found for the selected depth." />
              ) : (
                <DataTable
                  columns={[
                    {
                      key: 'ci',
                      label: 'Configuration Item',
                      render: (row) => (
                        <button type="button" className="link-button" onClick={() => setSelectedCiId(row.id)} style={{ textAlign: 'left' }}>
                          {ciDisplay(row)}{String(row.criticality || '').toLowerCase() === 'critical' ? <span className="badge" style={{ marginLeft: 8 }}>Critical</span> : null}
                        </button>
                      ),
                    },
                    { key: 'status', label: 'Status', render: (row) => CI_STATUS_LABELS[row.status] || row.status || '—' },
                    { key: 'criticality', label: 'Criticality', render: (row) => CRITICALITY_LABELS[row.criticality] || row.criticality || '—' },
                    {
                      key: 'actions',
                      label: 'Navigate',
                      render: (row) => (
                        <div className="table-actions">
                          <a className="btn-small" href={`#/cmdb/items/${row.id}`}>Open CI</a>
                          <a className="btn-small" href={`#/cmdb/items/${row.id}/dependencies`}>Dependencies</a>
                          <a className="btn-small" href={`#/cmdb/items/${row.id}/impact`}>Impact</a>
                        </div>
                      ),
                    },
                  ]}
                  rows={affectedCIs}
                  keyOf={(row) => row.id}
                  emptyTitle="No affected CIs."
                  emptyHint="No downstream configuration items found."
                />
              )}
            </div>

            <div className="panel panel-pad">
              <h2 style={{ marginTop: 0 }}>Selected Affected CI</h2>
              {!selectedCi ? (
                <EmptyState title="No CI selected." hint="Select an affected CI to view details and navigation actions." />
              ) : (
                <div>
                  <p><strong>{ciDisplay(selectedCi)}</strong></p>
                  <p className="muted">Status: {CI_STATUS_LABELS[selectedCi.status] || selectedCi.status || '—'} · Criticality: {CRITICALITY_LABELS[selectedCi.criticality] || selectedCi.criticality || '—'}</p>
                  <div className="table-actions" style={{ marginBottom: 12 }}>
                    <a className="btn-small" href={`#/cmdb/items/${selectedCi.id}`}>Open CI Detail</a>
                    <a className="btn-small" href={`#/cmdb/items/${selectedCi.id}/dependencies`}>View Dependencies</a>
                    <a className="btn-small" href={`#/cmdb/items/${selectedCi.id}/impact`}>Analyze Its Impact</a>
                    <a className="btn-small" href={`#/cmdb/items/${selectedCi.id}/relationships`}>Relationships</a>
                  </div>
                  {selectedCi.environment && <p><strong>Environment:</strong> {selectedCi.environment}</p>}
                  {selectedCi.department_name && <p><strong>Department:</strong> {selectedCi.department_name}</p>}
                </div>
              )}
            </div>
          </div>

          <div className="split-grid split-2" style={{ marginBottom: 16 }}>
            <div className="panel panel-pad">
              <h2 style={{ marginTop: 0 }}>Critical Dependencies & SPOFs</h2>
              <h3>Critical Dependencies</h3>
              {criticalDeps.length === 0 ? <p className="muted">None identified.</p> : (
                <ul>
                  {criticalDeps.map((d, i) => {
                    const cid = d.id ?? d.ci_id ?? d.configuration_item;
                    return <li key={`cd-${i}`}>{cid ? <a href={`#/cmdb/items/${cid}`}>{d.ci_number || d.name || `CI #${cid}`}</a> : (d.name || d.ci_number || JSON.stringify(d))} {d.criticality ? `(${d.criticality})` : ''}</li>;
                  })}
                </ul>
              )}
              <h3>Single Points of Failure</h3>
              {spofs.length === 0 ? <p className="muted">None identified.</p> : (
                <ul>
                  {spofs.map((s, i) => {
                    const cid = s.ci_id ?? s.id ?? s.configuration_item;
                    return <li key={`spof-${i}`}>{cid ? <a href={`#/cmdb/items/${cid}`}>{s.ci_number || s.ci_name || s.name || `CI #${cid}`}</a> : (s.name || JSON.stringify(s))} {s.dependent_count != null ? `— dependents: ${s.dependent_count}` : ''}</li>;
                  })}
                </ul>
              )}
            </div>
            <div className="panel panel-pad">
              <h2 style={{ marginTop: 0 }}>Affected Scope</h2>
              <h3>Services</h3>
              {services.length === 0 ? <p className="muted">No affected services reported.</p> : <ul>{services.map((s, i) => <li key={`svc-${i}`}>{s.name || s.service_name || `Service #${s.id || s.service_id || i}`}</li>)}</ul>}
              <h3>Departments</h3>
              {departments.length === 0 ? <p className="muted">No affected departments reported.</p> : <ul>{departments.map((d, i) => <li key={`dep-${i}`}>{d.name || d.department_name || `Department #${d.id || i}`}</li>)}</ul>}
              <h3>Owners</h3>
              {owners.length === 0 ? <p className="muted">No affected owners reported.</p> : <ul>{owners.map((o, i) => <li key={`own-${i}`}>{o.email || o.username || o.name || `User #${o.id || i}`}</li>)}</ul>}
              {(includeTickets || includeChanges) && (
                <>
                  <h3>Affected Tickets</h3>
                  {tickets.length === 0 ? <p className="muted">None or not included.</p> : <ul>{tickets.map((t, i) => <li key={`t-${i}`}>{t.ticket_number || t.id || JSON.stringify(t)} {t.status ? `(${t.status})` : ''}</li>)}</ul>}
                  <h3>Affected Changes</h3>
                  {changes.length === 0 ? <p className="muted">None or not included.</p> : <ul>{changes.map((c, i) => <li key={`c-${i}`}>{c.change_number || c.id || JSON.stringify(c)} {c.status ? `(${c.status})` : ''}</li>)}</ul>}
                </>
              )}
            </div>
          </div>

          <div className="panel panel-pad">
            <h2 style={{ marginTop: 0 }}>Risk Summary</h2>
            {Object.keys(risk).length === 0 ? (
              <p className="muted">No risk summary provided by backend.</p>
            ) : (
              <div className="split-grid split-3">
                {Object.entries(risk).map(([k, v]) => (
                  <div key={k}><strong>{k.replace(/_/g, ' ')}:</strong> {typeof v === 'object' ? JSON.stringify(v) : String(v)}</div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
