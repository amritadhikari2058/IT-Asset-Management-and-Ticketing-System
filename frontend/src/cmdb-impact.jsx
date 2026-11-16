import { useEffect, useState, useMemo } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, EmptyState, PageHeader, LoadingRows,
} from './components';
import {
  formatDate, formatDateTime, formatPercent, safeResults,
  ciStatusBadgeVariant, criticalityBadgeVariant,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function ImpactAnalysisPage({ match: { params: { id } } }) {
  const { role } = useAuth();
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
  const [riskSummary, setRiskSummary] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Load impact analysis from backend
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');

    const params = new URLSearchParams();
    if (proposedStatus) params.set('proposed_status', proposedStatus);
    params.set('depth', String(depth));
    if (includeTickets) params.set('include_tickets', 'true');
    if (includeChanges) params.set('include_changes', 'true');

    api.get(`${CMDB_API_CONTRACT.impactAnalysis.endpoint(Number(id))}?${params.toString()}`)
      .then((r) => {
        if (cancelled) return;
        setSourceCI(sourceCI || r.data); // store source CI data
      })
      .catch((e) => {
        if (cancelled) return;
        setError('Could not load impact analysis.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, proposedStatus, depth, includeTickets, includeChanges]);

  // Update state from impact response - called when API response arrives
  const processImpactResponse = (r) => {
    const data = r.data || {};
    setAffectedCIs(safeResults(data.affected_ci_ids));
    setAffectedServices(safeResults(data.affected_services));
    setAffectedDepartments(safeResults(data.affected_departments));
    setAffectedOwners(safeResults(data.affected_owners));
    setCriticalDeps(safeResults(data.critical_dependencies));
    setSinglePoints(safeResults(data.single_points_of_failure));
    setRiskSummary(data.risk_summary || '—');
  };

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB impact analysis access.
      </div>
    );
  }

  if (loading && !sourceCI) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading impact analysis...</p>
      </div>
    );
  }

  if (error && !sourceCI) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Impact Analysis"
        sub={`CI #${params.id} · Depth: ${depth}`}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Filter controls */}
      {loading ? null : (
        <div className="panel panel-pad mb-3">
          <div className="row-gap">
            <Field label="Proposed Status">
              <Select
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
                onChange={(e) => setIncludeTickets(e.target.value === 'true')}
                aria-label="Include tickets"
              >
                <option value="false">No</option>
                <option value="true">Yes</option>
              </Select>
            </Field>
            <Field label="Include Changes">
              <Select
                onChange={(e) => setIncludeChanges(e.target.value === 'true')}
                aria-label="Include changes"
              >
                <option value="false">No</option>
                <option value="true">Yes</option>
              </Select>
            </Field>
          </div>
        </div>
      )}

      {/* Impact results */}
      {loading ? null : (
        <div>
          <div className="panel panel-pad">
            <h2>Source CI</h2>
            {sourceCI && (
              <div>
                <strong>{sourceCI.ci_number || sourceCI.name}</strong> ({sourceCI.environment || '—'})
              </div>
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Affected CIs</h2>
            {affectedCIs.length > 0 ? (
              <ul className="mini-list">
                {affectedCIs.map((ciId) => {
                  const ci = sourceCI && sourceCI.id === String(ciId)
                    ? sourceCI
                    : {};
                  return <li key={ciId}>
                    {ci.ci_number || '—'} {ci.name || '—'}
                  </li>;
                })}
              </ul>
            ) : (
              <EmptyState
                title="No affected CIs"
                hint="Adjust filters or increase depth to see impacted items."
              />
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Affected Services</h2>
            {affectedServices.length > 0 ? (
              <ul className="mini-list">
                {affectedServices.map((svc) => (
                  <li key={svc}>{svc || '—'}</li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No affected services"
                hint="No services are affected by this change."
              />
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Affected Departments</h2>
            {affectedDepartments.length > 0 ? (
              <ul className="mini-list">
                {affectedDepartments.map((dept) => (
                  <li key={dept}>{dept || '—'}</li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No affected departments"
                hint="No departments are affected."
              />
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Affected Owners</h2>
            {affectedOwners.length > 0 ? (
              <ul className="mini-list">
                {affectedOwners.map((owner) => (
                  <li key={owner}>{owner || '—'}</li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No affected owners"
                hint="No owners are directly affected."
              />
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Critical Dependencies</h2>
            {criticalDeps.length > 0 ? (
              <ul className="mini-list">
                {criticalDeps.map((dep) => (
                  <li key={dep}>{dep || '—'}</li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No critical dependencies"
                hint="No critical dependencies identified."
              />
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Single Points of Failure</h2>
            {singlePoints.length > 0 ? (
              <ul className="mini-list">
                {singlePoints.map((sp) => (
                  <li key={sp}>{sp || '—'}</li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No single points of failure"
                hint="No single points of failure identified."
              />
            )}
          </div>

          <div className="panel panel-pad">
            <h2>Risk Summary</h2>
            <p>{riskSummary}</p>
          </div>

          {/* Clear wording */}
          <div className="panel panel-pad" style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #e2e6ea' }}>
            <p>
              <strong>Impact analysis is based on recorded CMDB relationships.</strong>
            </p>
            <p style={{ fontSize: '0.85em', color: 'var(--bs-secondary-color)' }}>
              Do not claim automatic discovery completeness. Impact analysis reflects
              recorded relationships only.
            </p>
          </div>
        </div>
      )}

      {/* Loading placeholder */}
      {loading && (
        <div className="panel panel-pad">
          <LoadingRows n={4} />
          <p>Loading impact analysis...</p>
        </div>
      )}
    </div>
  );
}