import { useCallback, useState, useEffect } from 'react';
import { useAuth } from '../../auth';
import { useApi } from '../../services/api-context';
import { PageHeader, LoadingPanel, ErrorPanel, EmptyState } from '../../components';

/** CMDB Item Detail — connects to backend ConfigurationItemViewSet at /api/cmdb/<id>/ */
export function CmdbItemDetail({ match }) {
  const auth = useAuth();
  const { request, loading, error, success } = useApi();
  const [item, setItem] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [errorState, setErrorState] = useState('');

  const load = useCallback(async () => {
    try {
      const resp = await request('GET', `/api/cmdb/${match.params.id}/`);
      setItem(resp.data);
      setLoaded(true);
    } catch (e) {
      setErrorState('Failed to load CMDB item detail.');
    }
  }, [match.params.id]);

  useEffect(() => { load(); }, [load]);

  if (!loaded) {
    return <LoadingPanel label="Loading CMDB item…"/>;
  }

  if (errorState) {
    return <ErrorPanel message={errorState} onRetry={load} />;
  }

  if (!item) {
    return <EmptyState title="CMDB Item">Item not found.</EmptyState>;
  }

  return (
    <div>
      <PageHeader title={item.name} subtitle={item.configuration_item_type} />
      <dl className="detail-grid">
        <dt>ID</dt><dd>{item.id}</dd>
        <dt>Type</dt><dd>{item.configuration_item_type}</dd>
        <dt>Name</dt><dd>{item.name}</dd>
        <dt>Status</dt><dd>{item.status}</dd>
        <dt>Last Updated</dt><dd>{item.last_updated}</dd>
        <dt>Owner</dt><dd>{item.owner}</dd>
      </dl>
    </div>
  );
}