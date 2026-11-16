import { useEffect, useState, useMemo } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, Button, ConfirmDialog,
} from './components';
import {
  formatDate, formatDateTime, ciStatusBadgeVariant,
  criticalityBadgeVariant, driftStatusBadgeVariant,
  safeResults, formatVerificationAge,
  CRITICALITY_LABELS, ENV_LABELS, STATUS_LABELS,
  RELATIONSHIP_STATUS_LABELS, RELATIONSHIP_TYPE_LABELS,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function DependencyMap({ match: { params: { id } } }) {
  const { role } = useAuth();
  const [depth, setDepth] = useState(3);
  const [view, setView] = useState('combined');
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [nodeCount, setNodeCount] = useState(0);
  const [cycleIndicator, setCycleIndicator] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [loadingNodes, setLoadingNodes] = useState(false);

  // Load dependency map from backend
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setNodes([]);
    setEdges([]);
    setNodeCount(0);
    setCycleIndicator(null);

    api.get(`${CMDB_API_CONTRACT.dependencyMap.endpoint(Number(id))}?depth=${depth}&view=${view}`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data || {};
        setNodes(safeResults(data.nodes));
        setEdges(safeResults(data.edges));
        setNodeCount(data.nodeCount || 0);
        setCycleIndicator(data.cycleIndicator || null);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError('Could not load dependency map.');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [depth, view, id]);

  // Load available CIs for selector
  useEffect(() => {
    let cancelled = false;
    setLoadingNodes(true);
    api.get('/cmdb/items/')
      .then((r) => { setNodes(safeResults(r.data)); })
      .catch(() => setNodes([]))
      .finally(() => { if (!cancelled) setLoadingNodes(false); });
    return () => { cancelled = true; };
  }, []);

  const handleDepthChange = (newDepth) => setDepth(newDepth);
  const handleViewChange = (newView) => setView(newView);

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB dependency map access.
      </div>
    );
  }

  if (loading && nodeCount === 0) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading dependency map...</p>
      </div>
    );
  }

  if (error && nodeCount === 0) {
    return <div className="error-summary" role="alert">{error}</div>;
  }

  // Node card
  const NodeCard = ({ node }) => {
    const nodeData = nodes.find((n) => n.id === node);
    if (!nodeData) return null;
    return (
      <div className="node-card" role="region"
        aria-label={`CI ${nodeData.ci_number || nodeData.name}`}>
        <div className="node-header">
          <span className="node-ci-number">{nodeData.ci_number || '—'}</span>
          <Badge kind="criticality" value={nodeData.criticality} />
        </div>
        <div className="node-details">
          <span className="node-name">{nodeData.name || '—'}</span>
          <span className="node-type">{nodeData.ci_type || '—'}</span>
          <span className="node-status">
            {nodeData.status && STATUS_LABELS[nodeData.status] || nodeData.status || '—'}
          </span>
        </div>
        <div className="node-meta">
          <span>{nodeData.environment && ENV_LABELS[nodeData.environment] || nodeData.environment || '—'}</span>
          <span>{formatDateTime(nodeData.updated_at)}</span>
        </div>
      </div>
    );
  };

  // Edge line
  const EdgeLine = ({ edge }) => {
    const edgeData = edges.find(
      (e) => e.id === edge || (e.source === edge.source && e.target === edge.target)
    );
    if (!edgeData) return null;
    return (
      <div className="edge-line" role="separator" aria-hidden="true">
        <span className="edge-label">
          {edge.relationship_type || '—'} {edge.status && RELATIONSHIP_STATUS_LABELS[edge.status] || edge.status || '—'}
        </span>
      </div>
    );
  };

  return (
    <div>
      <PageHeader
        title="Dependency Map"
        sub={`CI #${params.id} · Depth: ${depth} · View: ${view}`}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Controls */}
      <div className="panel panel-pad mb-3">
        <div className="row-gap">
          <label className="small muted">Depth:</label>
          <Select onChange={(e) => handleDepthChange(parseInt(e.target.value, 10))}
            aria-label="Dependency depth">
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
            <option value="4">4</option>
            <option value="5">5</option>
          </Select>
          <label className="small muted"> | </label>
          <label className="small muted">View:</label>
          <Select onChange={(e) => handleViewChange(e.target.value)}
            aria-label="Map view">
            <option value="upstream">Upstream</option>
            <option value="downstream">Downstream</option>
            <option value="combined">Combined</option>
          </Select>
        </div>
      </div>

      {/* Summary stats */}
      {nodeCount > 0 && (
        <div className="panel panel-pad">
          <div className="row-gap">
            <span>Nodes: {nodeCount}</span>
            {cycleIndicator && <Badge kind="driftStatus" value={cycleIndicator} />}
            <span>{edges.length} relationships</span>
          </div>
        </div>
      )

      {/* Node cards grid */}
      <div className="dependency-grid">
        {nodes.map((node, i) => (
          <div key={i} className="node-card">
            <div className="node-header">
              <span className="node-ci-number">{node.ci_number || 'CI'}</span>
            </div>
            <div className="node-details">
              <span className="node-name">{node.name || '—'}</span>
              <span className="node-type">{node.ci_type || '—'}</span>
            </div>
            <div className="node-meta">
              <span>{node.status && ciStatusBadgeVariant(node.status) || '—'}</span>
              <span>{node.environment && ENV_LABELS[node.environment] || node.environment || '—'}</span>
            </div>
          </div>
        ))}
      )

      {/* Edge connections */}
      {edges.length > 0 && (
        <div className="dependency-edges">
          {edges.map((edge, i) => (
            <div key={i} className="edge-line">
              <span className="edge-label">
                {edge.relationship_type || '—'} → {edge.target_ci_number || '—'}
              </span>
            </div>
          ))}
        </div>
      )

      {/* Table representation */}
      {nodes.length > 0 || edges.length > 0 && (
        <div className="panel panel-pad">
          <h4>Table Representation</h4>
          <DataTable
            columns={[
              { key: 'ci_number', label: 'CI Number' },
              { key: 'name', label: 'Name' },
              { key: 'ci_type', label: 'Type' },
              { key: 'status', label: 'Status', render: (v) => STATUS_LABELS[v] || v },
              { key: 'criticality', label: 'Criticality', render: (v) => CRITICALITY_LABELS[v] || v },
              { key: 'environment', label: 'Environment', render: (v) => ENV_LABELS[v] || v },
            ]}
            rows={edges.length > 0 ? edges : nodes}
            keyOf={(r) => r.ci_number || r.id}
            emptyTitle="No relationships"
          />
        </div>
      )
    </div>
  );
}