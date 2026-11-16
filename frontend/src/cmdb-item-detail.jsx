import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, EmptyState, PageHeader, LoadingRows, ErrorSummary, parseApiError,
} from './components';
import {
  formatDate, formatDateTime, formatPercent, ciStatusBadgeVariant,
  criticalityBadgeVariant, safeResults, formatVerificationAge,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function CiDetail({ match: { params: { id } } }) {
  const { role } = useAuth();
  const [header, setHeader] = useState(null);
  const [sections, setSections] = useState({
    overview: loading,
    ownership: loading,
    asset: loading,
    software_product: loading,
    service: loading,
    attributes: loading,
    relationships: loading,
    dependents: loading,
    impact: loading,
    tickets: loading,
    changes: loading,
    baselines: loading,
    drift: loading,
    verification: loading,
    history: loading,
  });
  const [error, setError] = useState('');
  const [loadingPrimary, setLoadingPrimary] = useState(true);

  // Load primary CI detail
  useEffect(() => {
    let cancelled = false;
    setLoadingPrimary(true);
    setError('');
    api.get(`${CMDB_API_CONTRACT.ciDetail.endpoint(Number(id))}`)
      .then((r) => {
        if (cancelled) return;
        setHeader(r.data);
      })
      .catch((e) => {
        if (cancelled) return;
        const parsed = parseApiError(e);
        setError(parsed.global || 'Could not load CI detail.');
      })
      .finally(() => { if (!cancelled) setLoadingPrimary(false); });
    return () => { cancelled = true; };
  }, [id]);

  // Load secondary sections - each independent so one failure doesn't blank the page
  const loadSection = async (sectionKey, endpointUrl) => {
    let cancelled = false;
    setSections(prev => ({ ...prev, [sectionKey]: loading }));
    try {
      const r = await api.get(endpointUrl);
      setSections(prev => ({ ...prev, [sectionKey]: r.data }));
    } catch (e) {
      // One failed secondary endpoint must not blank the whole detail page
      setSections(prev => ({ ...prev, [sectionKey]: { error: 'Failed to load section.' } }));
    } finally {
      if (!cancelled) {
        // No explicit finally needed since we set state in catch
      }
    }
  };

  // When primary loads, load all secondary sections
  useEffect(() => {
    if (!header || loadingPrimary) return;

    const ciId = Number(id);

    // 1. Ownership
    loadSection('ownership', `${CMDB_API_CONTRACT.ciDetail.endpoint(ciId)}`);

    // 2. Asset Link
    loadSection('asset', `/cmdb/items/${ciId}`); // Would be more specific

    // 3. Software Product Link
    loadSection('software_product', `/cmdb/items/${ciId}`);

    // 4. Service Link
    loadSection('service', `/cmdb/items/${ciId}`);

    // 5. Attributes
    loadSection('attributes', `/cmdb/items/${ciId}`);

    // 6. Relationships
    loadSection('relationships', `${CMDB_API_CONTRACT.ITEM_RELATIONSHIPS.endpoint(ciId)}`);

    // 7. Dependents
    loadSection('dependents', `${CMDB_API_CONTRACT.ITEM_DEPENDENTS.endpoint(ciId)}`);

    // 8. Impact Analysis
    loadSection('impact', `${CMDB_API_CONTRACT.ITEM_IMPACT.endpoint(ciId)}?depth=3`);

    // 9. Tickets
    loadSection('tickets', `${CMDB_API_CONTRACT.ITEM_TICKETS.endpoint(ciId)}`);

    // 10. Changes
    loadSection('changes', `${CMDB_API_CONTRACT.ITEM_CHANGES.endpoint(ciId)}`);

    // 11. Baselines
    loadSection('baselines', `${CMDB_API_CONTRACT.baselinesList.endpoint}?configuration_items=${ciId}`);

    // 12. Drift Findings
    loadSection('drift', `${CMDB_API_CONTRACT.driftList.endpoint}?ci=${ciId}`);

    // 13. Verification
    loadSection('verification', ``); // Would need specific endpoint

    // 14. History
    loadSection('history', `${CMDB_API_CONTRACT.ITEM_HISTORY.endpoint(ciId)}`);

  }, [id, header, loadingPrimary, role]);

  // Role-based access
  const canEdit = CMDB_PERMISSIONS.canEditCI(role);
  const canVerify = CMDB_PERMISSIONS.canVerifyCI(role);
  const canRetire = CMDB_PERMISSIONS.canRetireCI(role);

  // Employee denied
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB CI detail access.
      </div>
    );
  }

  if (loadingPrimary && !header) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={8} />
      </div>
    );
  }

  if (error && !header) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  const h = header || {};

  return (
    <div>
      <PageHeader
        title={h.ci_number ? `${h.ci_number} ${h.name}` : 'CI Detail'}
        sub=`${h.criticality || '—'} · ${h.status || '—'} · ${h.environment || '—'}`
      />

      {error && <ErrorSummary parsed={{ global: error }} />}

      {/* Header summary */}
      {header && (
        <div className="card card-outline card-height">
          <div className="card-head">
            <div className="head-left">
              <h1>{h.name}</h1>
              <div className="head-meta">
                <span>{h.ci_number || '—'}</span>
                <span>{h.status && STATUS_LABELS[h.status] || h.status || '—'}</span>
                <Badge kind="criticality" value={h.criticality} />
              </div>
            </div>
            <div className="head-right">
              <span>{h.record_version || '—'} | {h.last_verified_at ? formatDateTime(h.last_verified_at) : '—'}</span>
              <span>{h.monitoring_state || '—'}</span>
            </div>
          </div>
          <div className="card-body">
            <p>{h.description || 'No description.'}</p>
            {h.asset && <p><strong>Asset:</strong> {h.asset.name || h.asset.ci_number || h.asset.id}</p>}
            {h.software_product && <p><strong>Software Product:</strong> {h.software_product.name || h.software_product.ci_number || h.software_product.id}</p>}
            {h.service_catalogue_item && <p><strong>Service:</strong> {h.service_catalogue_item.name || h.service_catalogue_item.ci_number || h.service_catalogue_item.id}</p>}
          </div>
        </div>
      )}

      {/* Section tabs / accordion */}
      <div className="detail-sections">
        {/* Overview */}
        <div className="section" id="overview">
          <div className="section-head">
            <h2>Overview</h2>
          </div>
          <div className="section-body">
            {header && (
              <div className="detail-grid">
                <div className="detail-grid-row">
      <div className="detail-grid-col">
        <strong>CI Number</strong> {h.ci_number || '—'}
      </div>
      <div className="detail-grid-col">
        <strong>Type</strong> {h.ci_type_name || h.ci_type || '—'}
      </div>
      <div className="detail-grid-col">
        <strong>Status</strong> {h.status && STATUS_LABELS[h.status] || h.status || '—'}
      </div>
    </div>
    <div className="detail-grid-row">
      <div className="detail-grid-col">
        <strong>Lifecycle State</strong> {h.lifecycle_state && LIFECYCLE_LABELS[h.lifecycle_state] || h.lifecycle_state || '—'}
      </div>
      <div className="detail-grid-col">
        <strong>Criticality</strong> {h.criticality && criticalityBadgeVariant(h.criticality) || h.criticality || '—'}
      </div>
      <div className="detail-grid-col">
        <strong>Environment</strong> {h.environment && ENV_LABELS[h.environment] || h.environment || '—'}
      </div>
    </div>
    <div className="detail-grid-row">
      <div className="detail-grid-col">
        <strong>Last Verified</strong> {h.last_verified_at ? formatDateTime(h.last_verified_at) : 'Never'}
      </div>
      <div className="detail-grid-col">
        <strong>Monitoring State</strong> {h.monitoring_state && MONITORING_LABELS[h.monitoring_state] || h.monitoring_state || '—'}
      </div>
      <div className="detail-grid-col">
        <strong>Record Version</strong> {h.record_version || '—'}
      </div>
    </div>
              </div>
            )}
          </div>
        </div>

        {/* Ownership */}
        <div className="section" id="ownership">
          <div className="section-head">
            <h2>Ownership</h2>
          </div>
          <div className="section-body">
            {header && (
              <div>
                <strong>Owner</strong> {h.owner ? (h.owner.email || h.owner.employee_id || '—') : '—'}
                <br />
                <strong>Technical Owner</strong> {h.technical_owner ? (h.technical_owner.email || h.technical_owner.employee_id || '—') : '—'}
              </div>
            )}
          </div>
        </div>

        {/* Asset Link */}
        <div className="section" id="asset">
          <div className="section-head">
            <h2>Asset Link</h2>
          </div>
          <div className="section-body">
            {header && header.asset ? (
              <p>Linked asset ID: {header.asset.id}</p>
            ) : (
              <EmptyState
                title="No asset linked"
                hint="Link an asset via the CI form."
              />
            )}
          </div>
        </div>

        {/* Software Product Link */}
        <div className="section" id="software_product">
          <div className="section-head">
            <h2>Software Product Link</h2>
          </div>
          <div className="section-body">
            {header && header.software_product ? (
              <p>Linked software product ID: {header.software_product.id}</p>
            ) : (
              <EmptyState
                title="No software product linked"
                hint="Link a software product via the CI form."
              />
            )}
          </div>
        </div>

        {/* Service Link */}
        <div className="section" id="service">
          <div className="section-head">
            <h2>Service Link</h2>
          </div>
          <div className="section-body">
            {header && header.service_catalogue_item ? (
              <p>Linked service profile ID: {header.service_catalogue_item.id}</p>
            ) : (
              <EmptyState
                title="No service linked"
                hint="Link a service via the CI form."
              />
            )}
          </div>
        </div>

        {/* Attributes */}
        <div className="section" id="attributes">
          <div className="section-head">
            <h2>Attributes</h2>
          </div>
          <div className="section-body">
            {header && header.attributes ? (
              <pre className="attributes-json" style={{ whiteSpace: 'pre-wrap', fontSize: '0.85em' }}>
                {JSON.stringify(header.attributes, null, 2)}
              </pre>
            ) : (
              <EmptyState
                title="No attributes"
                hint="Attributes appear here when this CI has dynamic schema-defined fields."
              />
            )}
          </div>
        </div>

        {/* Relationships */}
        <div className="section" id="relationships">
          <div className="section-head">
            <h2>Relationships</h2>
          </div>
          <div className="section-body">
            {header && header.outgoing_relationships ? (
              <ul className="mini-list">
                {header.outgoing_relationships.map((rel) => (
                  <li key={rel.id} className="mini-item">
                    <span className="row-title">{rel.relationship_type}</span>
                    <span className="muted small">{rel.target_ci_number || '—'}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No relationships"
                hint="Relationships appear here when this CI has active links to other CIs."
              />
            )}
          </div>
        </div>

        {/* Dependents */}
        <div className="section" id="dependents">
          <div className="section-head">
            <h2>Dependents</h2>
          </div>
          <div className="section-body">
            {header && header.incoming_relationships ? (
              <ul className="mini-list">
                {header.incoming_relationships.map((rel) => (
                  <li key={rel.id} className="mini-item">
                    <span className="row-title">{rel.relationship_type}</span>
                    <span className="muted small">{rel.source_ci_number || '—'}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No dependents"
                hint="Dependents appear when other CIs link to this one."
              />
            )}
          </div>
        </div>

        {/* Impact Analysis */}
        <div className="section" id="impact">
          <div className="section-head">
            <h2>Impact Analysis</h2>
          </div>
          <div className="section-body">
            <p>
              Impact analysis is based on recorded CMDB relationships. 
              This uses the backend impact endpoint with bounded depth.
            </p>
            {header && (
              <div>
                <button className="btn-small" onClick={() => window.location.hash = `#/cmdb/items/${id}/impact?depth=3`}>
                  Run Impact Analysis
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Tickets */}
        <div className="section" id="tickets">
          <div className="section-head">
            <h2>Tickets</h2>
          </div>
          <div className="section-body">
            {header && header.ticket_links ? (
              <ul className="mini-list">
                {header.ticket_links.map((link) => (
                  <li key={link.id} className="mini-item">
                    <a href={`#/tickets/${link.ticket_id}`} target="_blank" rel="noopener">
                      Ticket {link.ticket_number || link.id}
                    </a>
                    <span className="muted small">({link.relation_type})</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No tickets"
                hint="Linked tickets appear here when this CI is associated with change or change requests."
              />
            )}
          </div>
        </div>

        {/* Changes */}
        <div className="section" id="changes">
          <div className="section-head">
            <h2>Changes</h2>
          </div>
          <div className="section-body">
            {header && header.change_links ? (
              <ul className="mini-list">
                {header.change_links.map((link) => (
                  <li key={link.id} className="mini-item">
                    <a href={`#/changes/${link.change_id}`} target="_blank" rel="noopener">
                      Change {link.change.change_number || link.id}
                    </a>
                    <span className="muted small">({link.change_role})</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No changes"
                hint="Linked changes appear here when this CI is involved in change requests."
              />
            )}
          </div>
        </div>

        {/* Baselines */}
        <div className="section" id="baselines">
          <div className="section-head">
            <h2>Baselines</h2>
          </div>
          <div className="section-body">
            <p>Baseline submissions and approvals are restricted to System Admins and IT Managers.</p>
          </div>
        </div>

        {/* Drift Findings */}
        <div className="section" id="drift">
          <div className="section-head">
            <h2>Drift Findings</h2>
          </div>
          <div className="section-body">
            <p>Configuration drift findings from baseline comparisons.</p>
          </div>
        </div>

        {/* Verification */}
        <div className="section" id="verification">
          <div className="section-head">
            <h2>Verification</h2>
          </div>
          <div className="section-body">
            {header && header.last_verified_at ? (
              <p>
                Last reviewed: {formatDateTime(header.last_verified_at)} by {header.verified_by ? header.verified_by.email || '—' : '—'}
              </p>
            ) : (
              <p>This CI has not been verified yet.</p>
            )}
            {canVerify && (
              <button className="btn-small" onClick={() => {
                // Trigger verification
                window.location.hash = `#/cmdb/items/${id}/verify`;
              }}>
                Verify CI
              </button>
            )}
          </div>
        </div>

        {/* History */}
        <div className="section" id="history">
          <div className="section-head">
            <h2>History</h2>
          </div>
          <div className="section-body">
            {header && header.history ? (
              <ul className="mini-list">
                {header.history.slice(0, 20).map((event) => (
                  <li key={event.id} className="mini-item">
                    <span className="muted small">{formatDateTime(event.created_at)}</span>
                    <span>{event.event_type}</span>
                    {event.detail && <span>{event.detail}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No history"
                hint="History records appear here when this CI is created, updated, verified, or retired."
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}