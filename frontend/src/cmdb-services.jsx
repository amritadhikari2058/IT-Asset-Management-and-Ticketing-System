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
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
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
          { key: 'service', label: 'Service', render: (row) => row.service_name || row.service || '—' },
          { key: 'service_tier', label: 'Tier', render: (row) => row.service_tier || '—' },
          { key: 'criticality', label: 'Criticality', render: (row) => CRITICALITY_LABELS[row.criticality] || row.criticality || '—' },
          { key: 'service_owner', label: 'Service Owner', render: (row) => row.service_owner_name || row.service_owner || '—' },
          { key: 'technical_owner', label: 'Tech Owner', render: (row) => row.technical_owner_name || row.technical_owner || '—' },
          { key: 'support_group', label: 'Support Group', render: (row) => row.support_group || '—' },
          { key: 'ci_count', label: 'CI Count', render: (row) => row.ci_count ?? '—' },
          { key: 'single_point_of_failure_count', label: 'SPOF Count', render: (row) => row.single_point_of_failure_count ?? '—' },
        ]}
        rows={serviceProfiles}
        keyOf={(r) => r.id}
        emptyTitle="No service profiles found."
        emptyHint="Service profiles are created when service catalogues are configured."
      />
    </div>
  );
}