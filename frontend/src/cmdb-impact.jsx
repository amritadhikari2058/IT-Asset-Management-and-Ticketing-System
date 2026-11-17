import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  EmptyState, PageHeader, LoadingRows, Field, Select,
} from './components';
import {
  safeResults, CMDB_API_CONTRACT,
} from './cmdb-utils';

export function ImpactAnalysisPage({ match: { params: { id } } }) {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [sourceCI, setSourceCI] = useState(null);
  const [proposedStatus, setProposedStatus] = useState('');
  const [depth, setDepth] = useState(3);
  const [includeTickets, setIncludeTickets] = useState(false);
  const [includeChanges, setIncludeChanges] = useState(false);
  const [affectedCIs, setAffectedCIs] = useState([]);
  const [affectedServices, setAffectedServices] = useState([]);
  const [affectedDepartments, setAffectedDepartments] = useState([]);
  const [affectedOwners, setAffectedOwners] = useState([]);
  const [criticalDeps, setCriticalDeps] = useState([]);
  const [singlePoints, setSinglePoints] = useState([]);
  const [riskSummary, setRiskSummary] = useState('—');
  const [truncation, setTruncation] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Load impact analysis from backend (bounded by depth)
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');

    const query = new URLSearchParams();
    if (proposedStatus) query.set('proposed_status', proposedStatus);
    query.set('depth', String(depth));
    if (includeTickets) query.set('include_tickets', 'true');
    if (includeChanges) query.set('include_changes', 'true');

    api.get(`${CMDB_API_CONTRACT.impactAnalysis.endpoint(Number(id))}?${query.toString()}`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data || {};
        setSourceCI(data.source_ci || null);
        setAffectedCIs(safeResults(data.affected_ci_ids));
        setAffectedServices(safeResults(data.affected_services));
        setAffectedDepartments(safeResults(data.affected_departments));
        setAffectedOwners(safeResults(data.affected_owners));
        setCriticalDeps(safeResults(data.critical_dependencies));
        setSinglePoints(safeResults(data.single_points_of_failure));
        setRiskSummary(data.risk_summary || '—');
        const warning = r.warning || data.warning
          || (data.metadata?.truncated ? 'Result exceeds depth limit.' : '');
        setTruncation(warning);
      })
      .catch(() => {
        if (cancelled) return;
        setError('Could not load impact analysis.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, proposedStatus, depth, includeTickets, includeChanges]);

  // Employees have no impact analysis access
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB impact analysis access.
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Impact Analysis"
        sub={`CI #${id} · Depth: ${depth}`}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {truncation && (
        <div className="error-summary" role="alert">
          Results truncated: {truncation}
        </div>
      )}

      {/* Read-only filter controls */}
      <div className="panel panel-pad mb-3">
        <div className="row-gap">
          <Field label="Proposed Status">
            <Select
              value={proposedStatus}
              onChange={(e) => setProposedStatus(e.target.value)}
              aria-label="Proposed status"
            >
              <option value="">No proposed status change</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="degraded">Degraded</option>
              <option value="failed">Failed</option>
              <option value="retired">Retired</option>
            </Select>
          </Field>
          <Field label="Maximum Depth">
            <Select
              value={String(depth)}
              onChange={(e) => setDepth(parseInt(e.target.value, 10))}
              aria-label="Maximum depth"
            >
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
            </Select>
          </Field>
          <Field label="Include Tickets">
            <Select
              value={String(includeTickets)}
              onChange={(e) => setIncludeTickets(e.target.value === 'true')}
              aria-label="Include tickets"
            >
              <option value="false">No</option>
              <option value="true">Yes</option>
            </Select>
          </Field>
          <Field label="Include Changes">
            <Select
              value={String(includeChanges)}
              onChange={(e) => setIncludeChanges(e.target.value === 'true')}
              aria-label="Include changes"
            >
              <option value="false">No</option>
              <option value="true">Yes</option>
            </Select>
          </Field>
        </div>
      </div>

      {loading ? (
        <div className="panel panel-pad">
          <LoadingRows n={4} />
          <p>Loading impact analysis...</p>
        </div>
      ) : (
        <div>
          <div className="panel panel-pad">
            <h2>Source CI</h2>
            {sourceCI ? (
              <div>
                <strong>{sourceCI.ci_number || sourceCI.name}</strong> ({sourceCI.environment || '—'})
              </div>
            ) : (
              <p className="muted">CI #{id}</p>
            )}
          </div>

          <ImpactSection title="Affected CIs" items={affectedCIs}>
            {(items) => (
              <ul className="mini-list">
                {items.map((ciId) => (
                  <li key={ciId} className="mini-item">
                    {sourceCI && String(sourceCI.id) === String(ciId)
                      ? `${sourceCI.ci_number || '—'} ${sourceCI.name || ''}`
                      : `CI #${ciId}`}
                  </li>
                ))}
              </ul>
            )}
          </ImpactSection>

          <ImpactSection title="Affected Services" items={affectedServices} />
          <ImpactSection title="Affected Departments" items={affectedDepartments} />
          <ImpactSection title="Affected Owners" items={affectedOwners} />
          <ImpactSection title="Critical Dependencies" items={criticalDeps} />
          <ImpactSection title="Single Points of Failure" items={singlePoints} />

          <div className="panel panel-pad">
            <h2>Risk Summary</h2>
            <p>{riskSummary}</p>
          </div>
        </div>
      )}

      {/* Clear wording */}
      <div className="panel panel-pad" style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #e2e6ea' }}>
        <p>
          <strong>Impact analysis is based on recorded CMDB relationships.</strong>
        </p>
        <p style={{ fontSize: '0.85em', color: 'var(--bs-secondary-color)' }}>
          Impact analysis reflects recorded relationships only.
        </p>
      </div>
    </div>
  );
}

function ImpactSection({ title, items, children }) {
  return (
    <div className="panel panel-pad">
      <h2>{title}</h2>
      {items.length > 0 ? (
        children ? children(items) : (
          <ul className="mini-list">
            {items.map((item) => (
              <li key={String(item)} className="mini-item">{String(item)}</li>
            ))}
          </ul>
        )
      ) : (
        <EmptyState title={`No ${title.toLowerCase()}`} hint="Adjust filters or increase depth to see results." />
      )}
    </div>
  );
}
