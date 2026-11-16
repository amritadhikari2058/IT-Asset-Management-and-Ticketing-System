import { useEffect, useState, useMemo } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, Tab, Tabs,
} from './components';
import {
  formatDate, formatDateTime, safeResults,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function CmdbReports() {
  const { role } = useAuth();
  const [reports, setReports] = useState(null);
  const [kind, setKind] = useState('coverage');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [range, setRange] = useState({ from: '', to: '' });

  // Load reports based on kind
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');

    const p = new URLSearchParams();
    if (range.from) p.set('date_from', range.from);
    if (range.to) p.set('date_to', range.to);

    api.get(`${CMDB_API_CONTRACT.reports.endpoint}?kind=${kind}${p.toString() ? `&${p.toString()}` : ''}`)
      .then((r) => { if (!cancelled) setReports(r.data); })
      .catch((e) => { setError('Could not load reports.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [kind, range]);

  // Filter options
  const filterOptions = useMemo(() => ({
    department: { label: 'Department', options: [] },
    ci_type: { label: 'CI Type', options: [] },
    environment: {
      label: 'Environment',
      options: [
        { value: 'production', label: 'Production' },
        { value: 'test', label: 'Test' },
        { value: 'staging', label: 'Staging' },
        { value: 'development', label: 'Development' },
      ],
    },
    criticality: {
      label: 'Criticality',
      options: [
        { value: 'critical', label: 'Critical' },
        { value: 'high', label: 'High' },
        { value: 'medium', label: 'Medium' },
        { value: 'low', label: 'Low' },
      ],
    },
    status: {
      label: 'Status',
      options: [
        { value: 'active', label: 'Active' },
        { value: 'inactive', label: 'Inactive' },
      ],
    },
  }), []);

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB reports access.
      </div>
    );
  }

  if (loading && !reports) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading reports...</p>
      </div>
    );
  }

  if (error && !reports) {
    return <div className="error-summary" role="alert">{error}</div>;
  }

  return (
    <div>
      <PageHeader
        title="CMDB Reports"
        sub="Aggregated CMDB reports and analysis"
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Kind tabs */}
      <Tabs
        value={kind}
        onValueChange={setKind}
        aria-label="Report kind"
      >
        <Tab value="coverage">Coverage</Tab>
        <Tab value="verification_age">Verification Age</Tab>
        <Tab value="orphans">Orphan CIs</Tab>
        <Tab value="ownership_gaps">Ownership Gaps</Tab>
        <Tab value="relationship_coverage">Relationship Coverage</Tab>
        <Tab value="drift">Drift</Tab>
        <Tab value="critical_deps">Critical Dependencies</Tab>
        <Tab value="asset_sync">Asset Synchronization</Tab>
        <Tab value="software_sync">Software Synchronization</Tab>
      </Tabs>

      {/* Filters */}
      {loading ? null : (
        <div className="panel panel-pad">
          <div className="row-gap">
            <Field label="Department">
              <Select
                onChange={(e) => {/* filter */}}
                  aria-label="Department">
                <option value="">All Departments</option>
              </Select>
            </Field>
            <Field label="CI Type">
              <Select
                onChange={(e} => {/* filter */}}
                  aria-label="CI Type">
                <option value="">All CI Types</option>
              </Select>
            </Field>
            <Field label="Environment">
              <Select
                onChange={(e} => {/* filter */}}
                  aria-label="Environment">
                <option value="">All Environments</option>
                {filterOptions.environment.options.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="Criticality">
              <Select
                onChange={(e} => {/* filter */}}
                  aria-label="Criticality">
                <option value="">All Criticalities</option>
                {filterOptions.criticality.options.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="Status">
              <Select
                onChange={(e} => {/* filter */}}
                  aria-label="Status">
                <option value="">All Statuses</option>
              </Select>
            </Field>
            <Input
              placeholder="Date range start..."
              onChange={(e) => setRange({ from: e.target.value, to: range.to })}
              type="date"
              disabled={false}
            />
            <Input
              placeholder="Date range end..."
              onChange={(e) => setRange({ from: range.from, to: e.target.value })}
              type="date"
              disabled={false}
            />
          </div>
        </div>
      )}

      {/* Report content */}
      {reports ? (
        <div className="panel panel-pad">
          {reports.rows && reports.rows.length > 0 ? (
            <DataTable
              columns={reports.columns || [
                { key: 'label', label: 'Metric' },
                { key: 'value', label: 'Value' },
                { key: 'count', label: 'Count' },
              ]}
              rows={reports.rows}
              keyOf={(r) => r.label}
              emptyTitle="No data."
              emptyHint="Adjust filters to see report data."
            />
          ) : (
            <EmptyState
              title="No data found"
              hint="Adjust filters and kind to see report results."
            />
          )}
          <p className="muted small">
            Generated {reports.generated_at ? formatDateTime(reports.generated_at) : '— ago}.
          </p>
        </div>
      ) : (
        <EmptyState
          title="No reports selected"
          hint="Select a report kind and adjust filters to see results."
        />
      )}

      {/* Summary KPIs area */}
      {reports && reports.summary && (
        <div className="panel panel-pad">
          <h4>Summary</h4>
          <div className="row-gap">
            {Object.entries(reports.summary).map(([k, v]) => (
              <div key={k} className="summary-row">
                <span className="summary-label">{k}</span>
                <span className="summary-value">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}