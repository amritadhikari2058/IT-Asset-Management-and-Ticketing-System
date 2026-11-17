import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, EmptyState, PageHeader, LoadingRows,
} from './components';
import { parseApiError } from './api-utils';
import {
  formatDateTime, ciStatusBadgeVariant, criticalityBadgeVariant,
  CI_STATUS_LABELS, CI_LIFECYCLE_LABELS, ENVIRONMENT_LABELS,
  MONITORING_STATE_LABELS, CMDB_API_CONTRACT, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function CiDetail({ match: { params: { id } } }) {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [header, setHeader] = useState(null);
  const [error, setError] = useState('');
  const [loadingPrimary, setLoadingPrimary] = useState(true);

  // Load primary CI detail
  useEffect(() => {
    let cancelled = false;
    setLoadingPrimary(true);
    setError('');
    api.get(CMDB_API_CONTRACT.ciDetail.endpoint(Number(id)))
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

  const canVerify = CMDB_PERMISSIONS.canVerifyCI(role);

  // Employees are denied CMDB CI detail access
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
        title={h.ci_number ? `${h.ci_number}` : 'CI Detail'}
        sub={`${CI_STATUS_LABELS[h.status] || h.status || '—'} · ${criticalityBadgeVariant(h.criticality)} · ${ENVIRONMENT_LABELS[h.environment] || h.environment || '—'}`}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Header summary */}
      <div className="card card-outline">
        <div className="card-head">
          <div className="head-left">
            <h1>{h.name || 'CI Detail'}</h1>
            <div className="head-meta">
              <span>{h.ci_number || '—'}</span>
              <span>{CI_STATUS_LABELS[h.status] || h.status || '—'}</span>
              <Badge kind="criticality" value={h.criticality} />
            </div>
          </div>
          <div className="head-right">
            <span>{h.record_version || '—'} | {h.last_verified_at ? formatDateTime(h.last_verified_at) : '—'}</span>
            <span>{MONITORING_STATE_LABELS[h.monitoring_state] || h.monitoring_state || '—'}</span>
          </div>
        </div>
        <div className="card-body">
          <p>{h.description || 'No description.'}</p>
          {h.asset && <p><strong>Asset:</strong> {h.asset.name || h.asset.ci_number || h.asset.id}</p>}
          {h.software_product && <p><strong>Software Product:</strong> {h.software_product.name || h.software_product.ci_number || h.software_product.id}</p>}
          {h.service_catalogue_item && <p><strong>Service:</strong> {h.service_catalogue_item.name || h.service_catalogue_item.ci_number || h.service_catalogue_item.id}</p>}
        </div>
      </div>

      {/* Sections */}
      <div className="detail-sections">
        <Section title="Overview">
          <div className="detail-grid">
            <div className="detail-grid-row">
              <div className="detail-grid-col"><strong>CI Number</strong> {h.ci_number || '—'}</div>
              <div className="detail-grid-col"><strong>Type</strong> {h.ci_type_name || h.ci_type || '—'}</div>
              <div className="detail-grid-col"><strong>Status</strong> {CI_STATUS_LABELS[h.status] || h.status || '—'}</div>
            </div>
            <div className="detail-grid-row">
              <div className="detail-grid-col"><strong>Lifecycle State</strong> {CI_LIFECYCLE_LABELS[h.lifecycle_state] || h.lifecycle_state || '—'}</div>
              <div className="detail-grid-col"><strong>Criticality</strong> {h.criticality || '—'}</div>
              <div className="detail-grid-col"><strong>Environment</strong> {ENVIRONMENT_LABELS[h.environment] || h.environment || '—'}</div>
            </div>
            <div className="detail-grid-row">
              <div className="detail-grid-col"><strong>Last Verified</strong> {h.last_verified_at ? formatDateTime(h.last_verified_at) : 'Never'}</div>
              <div className="detail-grid-col"><strong>Monitoring State</strong> {MONITORING_STATE_LABELS[h.monitoring_state] || h.monitoring_state || '—'}</div>
              <div className="detail-grid-col"><strong>Record Version</strong> {h.record_version || '—'}</div>
            </div>
          </div>
        </Section>

        <Section title="Ownership">
          <div>
            <strong>Owner</strong> {h.owner ? (h.owner.email || h.owner.employee_id || '—') : '—'}
            <br />
            <strong>Technical Owner</strong> {h.technical_owner ? (h.technical_owner.email || h.technical_owner.employee_id || '—') : '—'}
          </div>
        </Section>

        <Section title="Asset Link">
          {h.asset ? (
            <p>Linked asset ID: {h.asset.id}</p>
          ) : (
            <EmptyState title="No asset linked" hint="Link an asset via the CI form." />
          )}
        </Section>

        <Section title="Software Product Link">
          {h.software_product ? (
            <p>Linked software product ID: {h.software_product.id}</p>
          ) : (
            <EmptyState title="No software product linked" hint="Link a software product via the CI form." />
          )}
        </Section>

        <Section title="Attributes">
          {h.attributes && Object.keys(h.attributes).length ? (
            <pre className="attributes-json" style={{ whiteSpace: 'pre-wrap', fontSize: '0.85em' }}>
              {JSON.stringify(h.attributes, null, 2)}
            </pre>
          ) : (
            <EmptyState title="No attributes" hint="Attributes appear here when this CI has dynamic schema-defined fields." />
          )}
        </Section>

        <Section title="Relationships">
          {h.outgoing_relationships?.length ? (
            <ul className="mini-list">
              {h.outgoing_relationships.map((rel) => (
                <li key={rel.id} className="mini-item">
                  <span className="row-title">{rel.relationship_type}</span>
                  <span className="muted small">{rel.target_ci_number || '—'}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No relationships" hint="Relationships appear here when this CI has active links to other CIs." />
          )}
        </Section>

        <Section title="Dependents">
          {h.incoming_relationships?.length ? (
            <ul className="mini-list">
              {h.incoming_relationships.map((rel) => (
                <li key={rel.id} className="mini-item">
                  <span className="row-title">{rel.relationship_type}</span>
                  <span className="muted small">{rel.source_ci_number || '—'}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No dependents" hint="Dependents appear when other CIs link to this one." />
          )}
        </Section>

        <Section title="Impact Analysis">
          <p>
            Impact analysis is based on recorded CMDB relationships.
            This uses the backend impact endpoint with bounded depth.
          </p>
          <button
            type="button"
            className="btn-small"
            onClick={() => window.location.hash = `#/cmdb/items/${id}/impact?depth=3`}
          >
            Run Impact Analysis
          </button>
        </Section>

        <Section title="History">
          {h.history?.length ? (
            <ul className="mini-list">
              {h.history.slice(0, 20).map((event) => (
                <li key={event.id} className="mini-item">
                  <span className="muted small">{formatDateTime(event.created_at)}</span>
                  <span>{event.event_type}</span>
                  {event.detail && <span>{event.detail}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No history" hint="History records appear here when this CI is created, updated, verified, or retired." />
          )}
        </Section>

        <Section title="Verification">
          {h.last_verified_at ? (
            <p>Last reviewed: {formatDateTime(h.last_verified_at)} by {h.verified_by ? (h.verified_by.email || '—') : '—'}</p>
          ) : (
            <p>This CI has not been verified yet.</p>
          )}
          {canVerify && (
            <button
              type="button"
              className="btn-small"
              onClick={() => { window.location.hash = `#/cmdb/items/${id}/verify`; }}
            >
              Verify CI
            </button>
          )}
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="section">
      <div className="section-head"><h2>{title}</h2></div>
      <div className="section-body">{children}</div>
    </div>
  );
}
