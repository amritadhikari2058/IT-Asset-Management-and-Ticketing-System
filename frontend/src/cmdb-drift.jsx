import { useEffect, useState, useMemo } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, Button, ConfirmDialog,
} from './components';
import { parseApiError } from './api-utils';
import {
  formatDate, formatDateTime, driftStatusBadgeVariant, driftSeverityBadgeVariant,
  safeResults, formatVerificationAge,
  DRIFT_TYPE_LABELS, DRIFT_SEVERITY_LABELS, DRIFT_STATUS_LABELS,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function DriftFindingsPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [driftFindings, setDriftFindings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    ci: null,
    baseline: null,
    finding_type: '',
    severity: 'low',
    status: 'open',
    field_name: '',
    expected_value: '',
    actual_value: '',
    resolution_note: '',
  });

  // Load drift findings
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(CMDB_API_CONTRACT.driftList.endpoint)
      .then((r) => { if (!cancelled) setDriftFindings(r.data); })
      .catch((e) => { setError('Could not load drift findings.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Acknowledge drift
  const acknowledgeDrift = async (driftId) => {
    setError('');
    try {
      await api.post(`${CMDB_API_CONTRACT.driftList.endpoint}/${driftId}/acknowledge`);
      setDriftFindings(prev => {
        let cancelled = false;
        api.get(CMDB_API_CONTRACT.driftList.endpoint)
          .then((r) => { if (!cancelled) setDriftFindings(r.data); })
          .catch(() => {});
        return prev;
      });
    } catch (e) {
      setError(parseApiError(e).global || 'Could not acknowledge drift.');
    }
  };

  // Resolve drift
  const resolveDrift = async (driftId) => {
    setError('');
    const note = window.prompt('Enter resolution note:');
    if (note === null || note.trim() === '') return;
    try {
      await api.post(`${CMDB_API_CONTRACT.driftList.endpoint}/${driftId}/resolve`, {
        resolution_note: note.trim(),
      });
      setDriftFindings(prev => {
        let cancelled = false;
        api.get(CMDB_API_CONTRACT.driftList.endpoint)
          .then((r) => { if (!cancelled) setDriftFindings(r.data); })
          .catch(() => {});
        return prev;
      });
    } catch (e) {
      setError(parseApiError(e).global || 'Could not resolve drift.');
    }
  };

  // Employee denied
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB drift findings access.
      </div>
    );
  }

  if (loading && !driftFindings.length) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading drift findings...</p>
      </div>
    );
  }

  if (error && !driftFindings.length) {
    return <div className="error-summary" role="alert">{error}</div>;
  }

  return (
    <div>
      <PageHeader
        title="Configuration Drift"
        sub="Operational configuration drift findings"
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Filter controls */}
      {loading ? null : (
        <div className="panel panel-pad mb-3">
          <div className="row-gap">
            <Field label="Status">
              <Select
                onChange={(e) => {/* filter handling */}}
                  aria-label="Drift status">
                <option value="">All Statuses</option>
                <option value="open">Open</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="resolved">Resolved</option>
                <option value="accepted">Accepted</option>
                <option value="false_positive">False Positive</option>
              </Select>
            </Field>
            <Field label="Severity">
              <Select
                onChange={(e) => {/* filter handling */}}
                  aria-label="Drift severity">
                <option value="">All Severities</option>
                <option value="info">Info</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </Select>
            </Field>
            <Field label="Type">
              <Select
                onChange={(e) => {/* filter handling */}}
                  aria-label="Drift type">
                <option value="">All Types</option>
              </Select>
            </Field>
          </div>
        </div>
      )}

      {/* Drift findings table */}
      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'severity', label: 'Severity', render: (row) => DRIFT_SEVERITY_LABELS[row.severity] || row.severity || '—' },
            { key: 'finding_type', label: 'Finding Type', render: (row) => DRIFT_TYPE_LABELS[row.finding_type] || row.finding_type || '—' },
            { key: 'ci_number', label: 'CI', render: (row) => row.ci_number || '—' },
            { key: 'baseline', label: 'Baseline', render: (row) => row.baseline_name || row.baseline || '—' },
            { key: 'field_name', label: 'Field', render: (row) => row.field_name || '—' },
            { key: 'expected_value', label: 'Expected', render: (row) => row.expected_value ?? '—' },
            { key: 'actual_value', label: 'Actual', render: (row) => row.actual_value ?? '—' },
            { key: 'status', label: 'Status', render: (row) => DRIFT_STATUS_LABELS[row.status] || row.status || '—' },
            { key: 'detected_at', label: 'Detected', render: (row) => row.detected_at ? formatDateTime(row.detected_at) : '—' },
          ]}
          rows={driftFindings}
          keyOf={(r) => r.id}
          emptyTitle="No drift findings."
          emptyHint="Configuration drift findings from baseline comparisons."
        />
      </div>

      {/* Action buttons */}
      {driftFindings.length > 0 && (
        <div className="panel panel-pad mt-3">
          <Button kind="primary" onClick={() => acknowledgeDrift(driftFindings[0]?.id)}>
            Acknowledge
          </Button>
          <Button kind="danger" onClick={() => resolveDrift(driftFindings[0]?.id)}>
            Resolve
          </Button>
        </div>
      )}
    </div>
  );
}