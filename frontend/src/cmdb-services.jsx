import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { DataTable, EmptyState, Field, LoadingRows, PageHeader, Select } from './components';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS, CI_STATUS_LABELS, CRITICALITY_LABELS, safeResults } from './cmdb-utils';

function ciLabel(ci) {
  if (!ci) return '—';
  const num = ci.ci_number || `CI #${ci.id || ci.ci_id}`;
  const name = ci.name || ci.ci_name || '';
  return name ? `${num} — ${name}` : num;
}

export function ServiceMappingPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [profiles, setProfiles] = useState([]);
  const [links, setLinks] = useState([]);
  const [selectedServiceId, setSelectedServiceId] = useState('');
  const [graph, setGraph] = useState(null);
  const [impact, setImpact] = useState(null);
  const [spof, setSpof] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');

  const canView = CMDB_PERMISSIONS.canViewServiceMapping(role);

  useEffect(() => {
    let cancelled = false;
    if (!canView) { setLoading(false); // eslint-disable-line react/set-state-in-effect
      return undefined; }
    setLoading(true); // eslint-disable-line react/set-state-in-effect
    setError(''); // eslint-disable-line react/set-state-in-effect
    Promise.all([
      api.get(CMDB_API_CONTRACT.serviceMapping.endpoint),
      api.get('/cmdb/service-links/'),
    ])
      .then(([pRes, lRes]) => {
        if (cancelled) return;
        const p = safeResults(pRes.data?.results ?? pRes.data);
        setProfiles(p);
        setLinks(safeResults(lRes.data?.results ?? lRes.data));
        const firstService = p[0]?.service || p[0]?.service_id;
        if (firstService) setSelectedServiceId(String(firstService));
      })
      .catch((e) => { if (!cancelled) setError(e?.response?.data?.detail || 'Could not load service mapping data.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [canView]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedServiceId) { setGraph(null); // eslint-disable-line react/set-state-in-effect
      setImpact(null); // eslint-disable-line react/set-state-in-effect
      setSpof(null); // eslint-disable-line react/set-state-in-effect
      return undefined; }
    setDetailLoading(true); // eslint-disable-line react/set-state-in-effect
    setDetailError(''); // eslint-disable-line react/set-state-in-effect
    Promise.allSettled([
      api.get(`/cmdb/services/${selectedServiceId}/graph/`),
      api.get(`/cmdb/services/${selectedServiceId}/impact/`),
      api.get(`/cmdb/services/${selectedServiceId}/single-points-of-failure/`),
    ]).then((results) => {
      if (cancelled) return;
      const [g, i, s] = results;
      setGraph(g.status === 'fulfilled' ? g.value.data : null);
      setImpact(i.status === 'fulfilled' ? i.value.data : null);
      setSpof(s.status === 'fulfilled' ? s.value.data : null);
      const firstErr = results.find((r) => r.status === 'rejected');
      if (firstErr && g.status === 'rejected' && i.status === 'rejected' && s.status === 'rejected') {
        setDetailError(firstErr.reason?.response?.data?.detail || 'Could not load service graph/impact details.');
      }
    }).finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedServiceId]);

  const selectedProfile = useMemo(() => profiles.find((p) => String(p.service || p.service_id) === String(selectedServiceId)) || null, [profiles, selectedServiceId]);
  const serviceLinks = useMemo(() => links.filter((l) => String(l.service || l.service_id) === String(selectedServiceId)), [links, selectedServiceId]);
  const nodes = safeResults(graph?.nodes);
  const edges = safeResults(graph?.edges);
  const affectedCis = safeResults(impact?.affected_cis).length ? safeResults(impact?.affected_cis) : safeResults(impact?.affected_ci_ids).map((id) => ({ id, ci_number: `CI #${id}` }));
  const spofItems = safeResults(spof?.single_points_of_failure);

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no CMDB service mapping access.</div>;
  }

  return (
    <div>
      <PageHeader
        title="Service Mapping"
        sub="Service-to-CI visibility using existing CMDB service profiles, links, dependency graphs, impact, and SPOF data"
        actions={<a className="btn-small" href="#/cmdb/items">Configuration Items</a>}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {loading ? (
        <div className="panel panel-pad"><LoadingRows n={6} /></div>
      ) : profiles.length === 0 && links.length === 0 ? (
        <div className="panel panel-pad">
          <EmptyState title="No service mapping data found." hint="No service profiles or service-CI links are currently available from the backend." />
        </div>
      ) : (
        <>
          <div className="panel panel-pad" style={{ marginBottom: 16 }}>
            <div className="split-grid split-2">
              <Field label="Service (from profiles)">
                <Select value={selectedServiceId} onChange={(e) => setSelectedServiceId(e.target.value)}>
                  <option value="">Select a service</option>
                  {profiles.map((p) => {
                    const sid = p.service || p.service_id || p.id;
                    return <option key={p.id || sid} value={String(sid)}>{p.service_name || p.name || `Service #${sid}`}</option>;
                  })}
                </Select>
              </Field>
              <div className="muted" style={{ alignSelf: 'end' }}>
                Profiles: {profiles.length} · Links: {links.length} · Selected service links: {serviceLinks.length}
              </div>
            </div>
            {selectedProfile && (
              <div style={{ marginTop: 12 }}>
                <p><strong>{selectedProfile.service_name || selectedProfile.name || `Service #${selectedServiceId}`}</strong></p>
                <p className="muted">Criticality: {CRITICALITY_LABELS[selectedProfile.criticality] || selectedProfile.criticality || '—'} · Tier: {selectedProfile.service_tier || '—'} · Availability target: {selectedProfile.availability_target || '—'}</p>
              </div>
            )}
          </div>

          <div className="panel panel-pad" style={{ marginBottom: 16 }}>
            <h2 style={{ marginTop: 0 }}>Service Profiles</h2>
            <DataTable
              columns={[
                { key: 'service_name', label: 'Service', render: (row) => row.service_name || row.name || `Service #${row.service || row.id}` },
                { key: 'criticality', label: 'Criticality', render: (row) => CRITICALITY_LABELS[row.criticality] || row.criticality || '—' },
                { key: 'service_tier', label: 'Tier', render: (row) => row.service_tier || '—' },
                { key: 'owner', label: 'Owners', render: (row) => [row.service_owner_name, row.technical_owner_name].filter(Boolean).join(' / ') || '—' },
                { key: 'actions', label: 'Actions', render: (row) => <button type="button" className="btn-small" onClick={() => setSelectedServiceId(String(row.service || row.service_id || ''))}>View Mapping</button> },
              ]}
              rows={profiles}
              keyOf={(row) => row.id || row.service}
              emptyTitle="No service profiles."
              emptyHint="Service profiles are not available."
            />
          </div>

          {detailError && <div className="error-summary" role="alert">{detailError}</div>}
          {detailLoading ? (
            <div className="panel panel-pad"><LoadingRows n={5} /></div>
          ) : selectedServiceId ? (
            <>
              <div className="split-grid split-2" style={{ marginBottom: 16 }}>
                <div className="panel panel-pad">
                  <h2 style={{ marginTop: 0 }}>Linked Configuration Items</h2>
                  {serviceLinks.length === 0 ? (
                    <EmptyState title="No service-CI links." hint="No CI links were returned for the selected service." />
                  ) : (
                    <DataTable
                      columns={[
                        { key: 'ci', label: 'Configuration Item', render: (row) => {
                          const cid = row.configuration_item || row.configuration_item_id || row.ci;
                          return cid ? <a href={`#/cmdb/items/${cid}`}>{row.configuration_item_name || row.ci_number || `CI #${cid}`}</a> : '—';
                        } },
                        { key: 'role', label: 'Role', render: (row) => row.role || '—' },
                        { key: 'actions', label: 'Navigate', render: (row) => {
                          const cid = row.configuration_item || row.configuration_item_id || row.ci;
                          return cid ? <div className="table-actions"><a className="btn-small" href={`#/cmdb/items/${cid}`}>Open CI</a><a className="btn-small" href={`#/cmdb/items/${cid}/dependencies`}>Dependencies</a></div> : '—';
                        } },
                      ]}
                      rows={serviceLinks}
                      keyOf={(row, i) => row.id || i}
                      emptyTitle="No links."
                      emptyHint="No linked CIs."
                    />
                  )}
                </div>
                <div className="panel panel-pad">
                  <h2 style={{ marginTop: 0 }}>Service Impact Summary</h2>
                  {!impact ? <p className="muted">No impact data available for this service.</p> : (
                    <>
                      <p className="muted">Affected CIs: {impact.affected_count ?? affectedCis.length} · SPOFs: {safeResults(impact.single_points_of_failure).length} · Truncated: {impact.truncated ? 'Yes' : 'No'}</p>
                      {affectedCis.length === 0 ? <EmptyState title="No affected CIs reported." hint="Service impact endpoint returned no affected CIs." /> : (
                        <ul>
                          {affectedCis.slice(0, 20).map((ci, i) => {
                            const cid = ci.id || ci.ci_id;
                            return <li key={cid || i}>{cid ? <a href={`#/cmdb/items/${cid}`}>{ciLabel(ci)}</a> : ciLabel(ci)}</li>;
                          })}
                          {affectedCis.length > 20 && <li className="muted">+ {affectedCis.length - 20} more</li>}
                        </ul>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className="split-grid split-2">
                <div className="panel panel-pad">
                  <h2 style={{ marginTop: 0 }}>Service Dependency Graph (Nodes/Edges)</h2>
                  {!graph ? <p className="muted">No graph data available for this service.</p> : (
                    <>
                      <p className="muted">Nodes: {nodes.length} · Edges: {edges.length} {graph.cycleIndicator ? '· Cycle detected' : ''} {graph.truncated ? '· Truncated' : ''}</p>
                      {nodes.length === 0 ? <EmptyState title="No graph nodes." hint="Service graph returned no nodes." /> : (
                        <DataTable
                          columns={[
                            { key: 'ci', label: 'CI', render: (n) => {
                              const cid = n.id || n.ci_id;
                              return cid ? <a href={`#/cmdb/items/${cid}`}>{n.ci_number || `CI #${cid}`}{n.name ? ` — ${n.name}` : ''}</a> : (n.name || '—');
                            } },
                            { key: 'status', label: 'Status', render: (n) => CI_STATUS_LABELS[n.status] || n.status || '—' },
                            { key: 'criticality', label: 'Criticality', render: (n) => CRITICALITY_LABELS[n.criticality] || n.criticality || '—' },
                          ]}
                          rows={nodes.slice(0, 100)}
                          keyOf={(n, i) => n.id || n.ci_id || i}
                          emptyTitle="No nodes."
                          emptyHint="No nodes."
                        />
                      )}
                    </>
                  )}
                </div>
                <div className="panel panel-pad">
                  <h2 style={{ marginTop: 0 }}>Single Points of Failure</h2>
                  {spofItems.length === 0 ? (
                    <EmptyState title="No SPOFs identified." hint={spof ? 'No single points of failure reported for this service.' : 'SPOF data unavailable for this service.'} />
                  ) : (
                    <DataTable
                      columns={[
                        { key: 'ci', label: 'CI', render: (row) => {
                          const cid = row.ci_id || row.id;
                          return cid ? <a href={`#/cmdb/items/${cid}`}>{row.ci_number || row.ci_name || row.name || `CI #${cid}`}</a> : (row.name || '—');
                        } },
                        { key: 'dependents', label: 'Dependents', render: (row) => row.dependent_count ?? row.dependents ?? '—' },
                        { key: 'criticality', label: 'Criticality', render: (row) => CRITICALITY_LABELS[row.criticality] || row.criticality || '—' },
                      ]}
                      rows={spofItems}
                      keyOf={(row, i) => row.ci_id || row.id || i}
                      emptyTitle="No SPOFs."
                      emptyHint="None."
                    />
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="panel panel-pad"><EmptyState title="Select a service." hint="Choose a service profile to view linked CIs, graph, impact, and SPOF data." /></div>
          )}
        </>
      )}
    </div>
  );
}
