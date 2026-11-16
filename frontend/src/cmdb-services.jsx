import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, Button, ConfirmDialog,
} from './components';
import {
  formatDate, formatPercent, safeResults, CRITICALITY_LABELS,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
} from './cmdb-utils';

export function ServiceMappingPage() {
  const { role } = useAuth();
  const [serviceProfiles, setServiceProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Load service profiles
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(CMDB_API_CONTRACT.serviceMapping.endpoint)
      .then((r) => { if (!cancelled) setServiceProfiles(r.data); })
      .catch((e) => { setError('Could not load service profiles.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB service mapping access.
      </div>
    );
  }

  if (loading && !serviceProfiles.length) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading service profiles...</p>
      </div>
    );
  }

  if (error && !serviceProfiles.length) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Service Mapping"
        sub="Service profiles and CI links"
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      <DataTable
        columns={[
          { key: 'service', label: 'Service', render: (v) => v || '—' },
          { key: 'service_tier', label: 'Tier', render: (v) => v || '—' },
          { key: 'criticality', label: 'Criticality', render: (v) => CRITICALITY_LABELS[v] || v || '—' },
          { key: 'service_owner', label: 'Service Owner', render: (v) => v || '—' },
          { key: 'technical_owner', label: 'Tech Owner', render: (v) => v || '—' },
          { key: 'support_group', label: 'Support Group', render: (v) => v || '—' },
          { key: 'ci_count', label: 'CI Count' },
          { key: 'single_point_of_failure_count', label: 'SPOF Count', render: (v) => v || '—' },
        ]}
        rows={serviceProfiles}
        keyOf={(r) => r.id}
        emptyTitle="No service profiles found."
        emptyHint="Service profiles are created when service catalogues are configured."
      />
    </div>
  );
}