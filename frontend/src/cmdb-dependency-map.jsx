import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Badge, DataTable, EmptyState, Field, LoadingRows, PageHeader, Select } from './components';
import {
  CI_STATUS_LABELS,
  CRITICALITY_LABELS,
  RELATIONSHIP_TYPE_LABELS,
  formatDateTime,
  safeResults,
} from './cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS } from './cmdb';

function nodeIdOf(node) { return Number(node?.id ?? node?.ci_id ?? node); }

export function DependencyMap({ id: idProp, match }) {
  const id = Number(idProp ?? match?.params?.id);
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [depth, setDepth] = useState(3);
  const [view, setView] = useState('combined');
  const [graph, setGraph] = useState({ nodes: [], edges: [], nodeCount: 0, cycleIndicator: false, truncated: false, max_depth: 3 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!id) return undefined;
    setLoading(true);
    setError('');
    api.get(`/cmdb/items/${id}/dependencies/?depth=${depth}`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data || {};
        setGraph({
          nodes: safeResults(data.nodes),
          edges: safeResults(data.edges),
          nodeCount: data.nodeCount ?? data.nodes?.length ?? 0,
          cycleIndicator: !!data.cycleIndicator,
          truncated: !!data.truncated,
          max_depth: data.max_depth ?? depth,
        });
      })
      .catch((e) => {
        if (!cancelled) setError(e?.response?.data?.detail || 'Could not load dependency graph.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, depth]);

  const nodesById = useMemo(() => {
    const map = new Map();
    (graph.nodes || []).forEach((n) => map.set(nodeIdOf(n), n));
    return map;
  }, [graph.nodes]);

  const { upstreamEdges, downstreamEdges } = useMemo(() => {
    const edges = graph.edges || [];
    return {
      upstreamEdges: edges.filter((e) => Number(e.target_ci ?? e.target) === id || Number(e.target_id) === id),
      downstreamEdges: edges.filter((e) => Number(e.source_ci ?? e.source) === id || Number(e.source_id) === id),
    };
  }, [graph.edges, id]);

  const upstreamNodeIds = useMemo(() => new Set(upstreamEdges.map((e) => Number(e.source_ci ?? e.source ?? e.source_id))), [upstreamEdges]);
  const downstreamNodeIds = useMemo(() => new Set(downstreamEdges.map((e) => Number(e.target_ci ?? e.target ?? e.target_id))), [downstreamEdges]);

  const visibleNodes = useMemo(() => {
    if (view === 'upstream') return (graph.nodes || []).filter((n) => upstreamNodeIds.has(nodeIdOf(n)) || nodeIdOf(n) === id);
    if (view === 'downstream') return (graph.nodes || []).filter((n) => downstreamNodeIds.has(nodeIdOf(n)) || nodeIdOf(n) === id);
    return graph.nodes || [];
  }, [graph.nodes, view, upstreamNodeIds, downstreamNodeIds, id]);

  const visibleEdges = useMemo(() => {
    if (view === 'upstream') return upstreamEdges;
    if (view === 'downstream') return downstreamEdges;
    return graph.edges || [];
  }, [graph.edges, view, upstreamEdges, downstreamEdges]);

  const selectedNode = selectedNodeId != null ? nodesById.get(Number(selectedNodeId)) : (nodesById.get(id) || null);
  const selectedEdges = useMemo(() => {
    if (!selectedNode) return { incoming: [], outgoing: [] };
    const nid = nodeIdOf(selectedNode);
    const edges = graph.edges || [];
    return {
      incoming: edges.filter((e) => Number(e.target_ci ?? e.target ?? e.target_id) === nid),
      outgoing: edges.filter((e) => Number(e.source_ci ?? e.source ?? e.source_id) === nid),
    };
  }, [selectedNode, graph.edges]);

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no dependency map access.</div>;
  }

  const ciLabel = (nodeId) => {
    const n = nodesById.get(Number(nodeId));
    if (!n) return `CI #${nodeId}`;
    return `${n.ci_number || `CI #${n.id}`} — ${n.name || 'Unnamed'}`;
  };

  const nodeColumns = [
    {
      key: 'ci',
      label: 'Configuration Item',
      render: (node) => {
        const nid = nodeIdOf(node);
        const critical = String(node.criticality || '').toLowerCase() === 'critical';
        return (
          <button type="button" className="link-button" onClick={() => setSelectedNodeId(nid)} style={{ textAlign: 'left' }}>
            <strong>{node.ci_number || `CI #${nid}`}</strong> — {node.name || 'Unnamed'}
            {nid === id ? ' (current)' : ''}
            {critical ? <span className="badge" style={{ marginLeft: 8 }}>Critical</span> : null}
          </button>
        );
      },
    },
    { key: 'status', label: 'Status', render: (n) => CI_STATUS_LABELS[n.status] || n.status || '—' },
    { key: 'criticality', label: 'Criticality', render: (n) => CRITICALITY_LABELS[n.criticality] || n.criticality || '—' },
    { key: 'ci_type_name', label: 'Type', render: (n) => n.ci_type_name || n.ci_type || '—' },
    {
      key: 'direction',
      label: 'Relation to Current CI',
      render: (n) => {
        const nid = nodeIdOf(n);
        if (nid === id) return 'Current CI';
        const up = upstreamNodeIds.has(nid);
        const down = downstreamNodeIds.has(nid);
        if (up && down) return 'Upstream & downstream';
        if (up) return 'Upstream (depends on / feeds into context)';
        if (down) return 'Downstream (impacted by current CI)';
        return 'Connected';
      },
    },
    {
      key: 'actions',
      label: 'Actions',
      render: (n) => (
        <div className="table-actions">
          <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(n)}`}>Open CI</a>
          <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(n)}/dependencies`}>Dependencies</a>
          <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(n)}/impact`}>Impact</a>
        </div>
      ),
    },
  ];

  const edgeColumns = [
    {
      key: 'source',
      label: 'Source CI',
      render: (e) => {
        const sid = Number(e.source_ci ?? e.source ?? e.source_id);
        return <a href={`#/cmdb/items/${sid}`}>{ciLabel(sid)}</a>;
      },
    },
    { key: 'direction', label: 'Direction', render: () => '→' },
    {
      key: 'target',
      label: 'Target CI',
      render: (e) => {
        const tid = Number(e.target_ci ?? e.target ?? e.target_id);
        return <a href={`#/cmdb/items/${tid}`}>{ciLabel(tid)}</a>;
      },
    },
    { key: 'relationship_type', label: 'Relationship', render: (e) => RELATIONSHIP_TYPE_LABELS[e.relationship_type || e.type] || e.relationship_type || e.type || '—' },
  ];

  return (
    <div>
      <PageHeader
        title="Dependency Map"
        sub={`Upstream and downstream dependencies for CI #${id}`}
        actions={(
          <>
            <a className="btn-small" href={`#/cmdb/items/${id}`}>Back to CI</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/impact`}>Impact Analysis</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/relationships`}>Relationships</a>
          </>
        )}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="split-grid split-4">
          <Field label="Depth">
            <Select value={String(depth)} onChange={(e) => setDepth(Number(e.target.value))} aria-label="Dependency depth">
              {[1, 2, 3, 4, 5].map((d) => <option key={d} value={String(d)}>{d}</option>)}
            </Select>
          </Field>
          <Field label="View">
            <Select value={view} onChange={(e) => setView(e.target.value)} aria-label="Dependency view">
              <option value="combined">Combined (upstream + downstream)</option>
              <option value="upstream">Upstream only</option>
              <option value="downstream">Downstream only</option>
            </Select>
          </Field>
          <div className="muted" style={{ alignSelf: 'end' }}>Nodes: {graph.nodeCount || visibleNodes.length}</div>
          <div className="muted" style={{ alignSelf: 'end' }}>Edges: {visibleEdges.length}</div>
        </div>
        {(graph.cycleIndicator || graph.truncated) && (
          <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
            {graph.cycleIndicator && <div className="notice">Cycle detected in dependency traversal. Graph is bounded to prevent infinite loops.</div>}
            {graph.truncated && <div className="notice">Results truncated at the backend safety limit. Reduce depth or inspect specific branches to avoid excessively large graphs.</div>}
          </div>
        )}
      </div>

      {loading ? (
        <div className="panel panel-pad"><LoadingRows n={6} /></div>
      ) : visibleNodes.length === 0 ? (
        <div className="panel panel-pad">
          <EmptyState title="No dependencies found." hint="This CI has no recorded upstream/downstream relationships for the selected view and depth." />
        </div>
      ) : (
        <>
          <div className="split-grid split-2" style={{ marginBottom: 16 }}>
            <div className="panel panel-pad">
              <h2 style={{ marginTop: 0 }}>Connected Configuration Items</h2>
              <p className="muted">Select a node to inspect details. Critical CIs are highlighted. Use actions to navigate to CI detail, dependency, or impact views.</p>
              <DataTable columns={nodeColumns} rows={visibleNodes} keyOf={(n) => nodeIdOf(n)} emptyTitle="No nodes" emptyHint="No nodes for selected view." />
            </div>
            <div className="panel panel-pad">
              <h2 style={{ marginTop: 0 }}>Selected Node Details</h2>
              {!selectedNode ? (
                <EmptyState title="No node selected." hint="Select a configuration item from the table." />
              ) : (
                <div>
                  <p><strong>{selectedNode.ci_number || `CI #${nodeIdOf(selectedNode)}`}</strong> — {selectedNode.name || 'Unnamed'}</p>
                  <p className="muted">Status: {CI_STATUS_LABELS[selectedNode.status] || selectedNode.status || '—'} · Criticality: {CRITICALITY_LABELS[selectedNode.criticality] || selectedNode.criticality || '—'} · Type: {selectedNode.ci_type_name || selectedNode.ci_type || '—'}</p>
                  <div className="table-actions" style={{ marginBottom: 12 }}>
                    <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(selectedNode)}`}>Open CI Detail</a>
                    <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(selectedNode)}/dependencies`}>View Dependencies</a>
                    <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(selectedNode)}/impact`}>View Impact</a>
                    <a className="btn-small" href={`#/cmdb/items/${nodeIdOf(selectedNode)}/relationships`}>Relationships</a>
                  </div>
                  <h3>Incoming (upstream into selected node)</h3>
                  {selectedEdges.incoming.length === 0 ? <p className="muted">None in current graph.</p> : (
                    <ul>
                      {selectedEdges.incoming.map((e, i) => {
                        const sid = Number(e.source_ci ?? e.source ?? e.source_id);
                        return <li key={`in-${i}`}><a href={`#/cmdb/items/${sid}`}>{ciLabel(sid)}</a> — {RELATIONSHIP_TYPE_LABELS[e.relationship_type || e.type] || e.relationship_type || e.type || 'relationship'} → selected</li>;
                      })}
                    </ul>
                  )}
                  <h3>Outgoing (downstream from selected node)</h3>
                  {selectedEdges.outgoing.length === 0 ? <p className="muted">None in current graph.</p> : (
                    <ul>
                      {selectedEdges.outgoing.map((e, i) => {
                        const tid = Number(e.target_ci ?? e.target ?? e.target_id);
                        return <li key={`out-${i}`}>selected → <a href={`#/cmdb/items/${tid}`}>{ciLabel(tid)}</a> — {RELATIONSHIP_TYPE_LABELS[e.relationship_type || e.type] || e.relationship_type || e.type || 'relationship'}</li>;
                      })}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="panel panel-pad">
            <h2 style={{ marginTop: 0 }}>Dependency Edges ({view})</h2>
            <p className="muted">Direction: source CI → target CI. Use this to understand upstream/downstream flow and navigate connected items.</p>
            <DataTable columns={edgeColumns} rows={visibleEdges} keyOf={(e, i) => `${e.id || i}-${e.source_ci || e.source}-${e.target_ci || e.target}`} emptyTitle="No edges" emptyHint="No relationship edges in the selected view." />
          </div>
        </>
      )}
    </div>
  );
}
