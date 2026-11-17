import { useEffect, useState, useMemo } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows, Pager,
  Field, Select, Input, ConfirmDialog, useTableColumns,
} from './components';
import {
  formatDate, formatDateTime, formatPercent, ciStatusBadgeVariant,
  criticalityBadgeVariant, safeResults, formatVerificationAge,
  buildCIListUrl,
} from './cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS } from './cmdb';

const STATUS_LABELS = {
  planned: 'Planned', active: 'Active', inactive: 'Inactive',
  maintenance: 'Maintenance', degraded: 'Degraded', failed: 'Failed',
  retired: 'Retired', disposed: 'Disposed', unknown: 'Unknown',
};
const LIFECYCLE_LABELS = {
  proposed: 'Proposed', ordered: 'Ordered', received: 'Received',
  installed: 'Installed', operational: 'Operational',
  under_change: 'Under Change', retired: 'Retired', disposed: 'Disposed',
};
const CRITICALITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };
const ENV_LABELS = {
  development: 'Development', test: 'Test', staging: 'Staging',
  production: 'Production', disaster_recovery: 'Disaster Recovery',
  office: 'Office', other: 'Other',
};
const SOURCE_LABELS = { manual: 'Manual', asset_sync: 'Asset Sync',
  licensing_sync: 'Licensing Sync', discovery: 'Discovery',
  import: 'Import', integration: 'Integration' };
const MONITORING_LABELS = { monitored: 'Monitored', not_monitored: 'Not Monitored',
  not_applicable: 'Not Applicable', unknown: 'Unknown' };
const DATA_CLASS_LABELS = { public: 'Public', internal: 'Internal',
  confidential: 'Confidential', restricted: 'Restricted', unknown: 'Unknown' };
const IMPACT_LABELS = { none: 'None', documentation_only: 'Documentation Only',
  configuration: 'Configuration', data_integrity_impact: 'Data Integrity Impact' };

// ── Safe pagination helper ──────────────────────────────────────────
function usePaginatedApiGet(endpoint, initialParams = {}) {
  const [params, setParams] = useState(() => ({ ...initialParams, page: 1 }));
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    const url = buildCIListUrl(params);
    api.get(`${endpoint}${url}`).then(
      (r) => {
        if (cancelled) return;
        const data = r.data;
        const results = Array.isArray(data) ? data : (data?.results ?? []);
        setItems(results);
        setCount(data.count ?? results.length);
      }
    ).catch(() => {
      if (cancelled) return;
      setError('Could not load CI list.');
      setCount(0);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [params, endpoint, reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  const goToPage = (pageNum) => {
    setParams({ ...params, page: pageNum });
  };

  return {
    items, count, loading, error, params,
    setParams, reload, goToPage,
  };
}

// ── CI List component ────────────────────────────────────────────────

export function CmdbItemsList() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [filters, setFilters] = useState({});
  useTableColumns('cmdb-items', [
    'ci_number', 'name', 'ci_type', 'status', 'lifecycle_state',
    'criticality', 'environment', 'department', 'location', 'owner',
    'technical_owner', 'asset', 'software_product', 'service',
    'last_verified_at', 'updated_at',
  ], [
    'ci_number', 'name', 'status', 'criticality',
    'environment', 'department', 'location', 'owner',
  ]);

  const { items, count, loading, error, params, setParams, goToPage } =
    usePaginatedApiGet(CMDB_API_CONTRACT.ciList.endpoint, {
      page: 1,
    });

  // Role-based action availability
  const canCreate = CMDB_PERMISSIONS.canCreateCI(role);
  const canEdit = CMDB_PERMISSIONS.canEditCI(role);
  const canVerify = CMDB_PERMISSIONS.canVerifyCI(role);
  const canRetire = CMDB_PERMISSIONS.canRetireCI(role);
  const canViewDetail = CMDB_PERMISSIONS.canViewCIDetail(role);

  // Build filter options UI
  const filterOptions = useMemo(() => ({
    status: {
      label: 'Status',
      options: [
        { value: 'planned', label: STATUS_LABELS.planned },
        { value: 'active', label: STATUS_LABELS.active },
        { value: 'inactive', label: STATUS_LABELS.inactive },
        { value: 'maintenance', label: STATUS_LABELS.maintenance },
        { value: 'degraded', label: STATUS_LABELS.degraded },
        { value: 'failed', label: STATUS_LABELS.failed },
        { value: 'retired', label: STATUS_LABELS.retired },
        { value: 'disposed', label: STATUS_LABELS.disposed },
      ],
    },
    criticality: {
      label: 'Criticality',
      options: [
        { value: 'low', label: CRITICALITY_LABELS.low },
        { value: 'medium', label: CRITICALITY_LABELS.medium },
        { value: 'high', label: CRITICALITY_LABELS.high },
        { value: 'critical', label: CRITICALITY_LABELS.critical },
      ],
    },
    environment: {
      label: 'Environment',
      options: [
        { value: 'development', label: ENV_LABELS.development },
        { value: 'test', label: ENV_LABELS.test },
        { value: 'staging', label: ENV_LABELS.staging },
        { value: 'production', label: ENV_LABELS.production },
        { value: 'disaster_recovery', label: ENV_LABELS.disaster_recovery },
        { value: 'office', label: ENV_LABELS.office },
        { value: 'other', label: ENV_LABELS.other },
      ],
    },
    source: {
      label: 'Source',
      options: [
        { value: 'manual', label: SOURCE_LABELS.manual },
        { value: 'asset_sync', label: SOURCE_LABELS.asset_sync },
        { value: 'licensing_sync', label: SOURCE_LABELS.licensing_sync },
        { value: 'discovery', label: SOURCE_LABELS.discovery },
        { value: 'import', label: SOURCE_LABELS.import },
        { value: 'integration', label: SOURCE_LABELS.integration },
      ],
    },
    verified: {
      label: 'Verified',
      options: [
        { value: 'true', label: 'Yes' },
        { value: 'false', label: 'No' },
      ],
    },
    monitoring_state: {
      label: 'Monitoring State',
      options: [
        { value: 'monitored', label: MONITORING_LABELS.monitored },
        { value: 'not_monitored', label: MONITORING_LABELS.not_monitored },
        { value: 'not_applicable', label: MONITORING_LABELS.not_applicable },
        { value: 'unknown', label: MONITORING_LABELS.unknown },
      ],
    },
    data_classification: {
      label: 'Data Classification',
      options: [
        { value: 'public', label: DATA_CLASS_LABELS.public },
        { value: 'internal', label: DATA_CLASS_LABELS.internal },
        { value: 'confidential', label: DATA_CLASS_LABELS.confidential },
        { value: 'restricted', label: DATA_CLASS_LABELS.restricted },
        { value: 'unknown', label: DATA_CLASS_LABELS.unknown },
      ],
    },
    validated_system_impact: {
      label: 'Validated-System Impact',
      options: [
        { value: 'none', label: IMPACT_LABELS.none },
        { value: 'documentation_only', label: IMPACT_LABELS.documentation_only },
        { value: 'configuration', label: IMPACT_LABELS.configuration },
        { value: 'data_integrity_impact', label: IMPACT_LABELS.data_integrity_impact },
      ],
    },
  }), []);

  // Apply/clear filters
  const applyFilters = () => setParams({ ...params, page: 1 });
  const clearFilters = () => {
    setFilters({});
    setParams({ page: 1 });
  };

  // Build DataTable columns from saved table state
  const columns = useMemo(() => {
    const base = [
      { key: 'ci_number', label: 'CI Number' },
      { key: 'name', label: 'Name' },
      { key: 'ci_type', label: 'Type' },
      { key: 'status', label: 'Status' },
      { key: 'lifecycle_state', label: 'Lifecycle' },
      { key: 'criticality', label: 'Criticality' },
      { key: 'environment', label: 'Environment' },
      { key: 'department', label: 'Department' },
      { key: 'location', label: 'Location' },
      { key: 'owner', label: 'Owner' },
      { key: 'technical_owner', label: 'Tech Owner' },
      { key: 'asset', label: 'Asset' },
      { key: 'software_product', label: 'Software Product' },
      { key: 'service', label: 'Service' },
      { key: 'last_verified_at', label: 'Last Verified' },
      { key: 'updated_at', label: 'Updated' },
    ];

    // Renderer for each column
    const renderers = {
      ci_number: (val) => val || '—',
      name: (val) => val || '—',
      ci_type: (val) => val || '—',
      status: (val) => STATUS_LABELS[val] ?? val,
      lifecycle_state: (val) => LIFECYCLE_LABELS[val] ?? val,
      criticality: (val) => CRITICALITY_LABELS[val] ?? val,
      environment: (val) => ENV_LABELS[val] ?? val,
      department: (val) => val || '—',
      location: (val) => val || '—',
      owner: (val) => val || '—',
      technical_owner: (val) => val || '—',
      asset: (val) => val || '—',
      software_product: (val) => val || '—',
      service: (val) => val || '—',
      last_verified_at: (val) => val ? formatDateTime(val) : '—',
      updated_at: (val) => val ? formatDateTime(val) : '—',
    };

    return base.map((c) => ({
      ...c,
      render: (row) => renderers[c.key](row[c.key]),
      sortable: true,
    }));
  }, []);

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB CI list access.
      </div>
    );
  }

  if (loading && items.length === 0) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={8} />
      </div>
    );
  }
  if (error && items.length === 0) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Configuration Items"
        sub={`${count} CIs`}
        actions={
          <>
            {canCreate && (
              <button className="btn-primary" onClick={() => window.location.hash = '#/cmdb/items/new'}>
                + New CI
              </button>
            )}
            <button className="btn-small" onClick={clearFilters}>Clear filters</button>
          </>
        }
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      <DataTable
        columns={columns}
        rows={items}
        keyOf={(r) => r.id ?? r.ci_number}
        emptyTitle="No configuration items found."
        emptyHint="Adjust filters to find CIs."
        selectable={canEdit}
        onSelect={({ id }) => window.location.hash = `#/cmdb/items/${id}`}
      />

      {/* Pager */}
      {count > 50 && (
        <div className="panel panel-pad">
          <Pager
            count={Math.ceil(count / 50)}
            hasNext={params.page < Math.ceil(count / 50)}
            hasPrev={params.page > 1}
            onPrev={() => goToPage(params.page - 1)}
            onNext={() => goToPage(params.page + 1)}
            busy={loading}
            pageLabel={`Page ${params.page}`}
          />
        </div>
      )}

      {/* Filter panel */}
      {loading ? null : (
        <div className="panel panel-pad" style={{ marginTop: 20 }}>
          <h4>Filters</h4>
          <div className="row-gap">
            <Select
              className="input input-auto"
              onChange={(v) => setFilters({ ...filters, status: v })}
              disabled={loading}
              aria-label="Status filter"
            >
              <option value="">All Statuses</option>
              {filterOptions.status.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
            <Select
              className="input input-auto"
              onChange={(v) => setFilters({ ...filters, criticality: v })}
              disabled={loading}
              aria-label="Criticality filter"
            >
              <option value="">All Criticalities</option>
              {filterOptions.criticality.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
            <Select
              className="input input-auto"
              onChange={(v) => setFilters({ ...filters, environment: v })}
              disabled={loading}
              aria-label="Environment filter"
            >
              <option value="">All Environments</option>
              {filterOptions.environment.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
            <Select
              className="input input-auto"
              onChange={(v) => setFilters({ ...filters, source: v })}
              disabled={loading}
              aria-label="Source filter"
            >
              <option value="">All Sources</option>
              {filterOptions.source.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
            <Select
              className="input input-auto"
              onChange={(v) => setFilters({ ...filters, verified: v })}
              disabled={loading}
              aria-label="Verified filter"
            >
              <option value="">All Verified</option>
              {filterOptions.verified.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
            <Input
              placeholder="Search CI number or name..."
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
              disabled={loading}
              aria-label="Global search"
            />
          </div>
        </div>
      )}
    </div>
  );
}