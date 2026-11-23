import { useCallback, useState, useEffect } from 'react';
import { useApi } from '../../services/api-context';
import { PageHeader, LoadingPanel, ErrorPanel, EmptyState } from '../../components';

/** CMDB Item Detail — connects to backend ConfigurationItemViewSet at /api/cmdb/<id>/ */
export function CmdbItemDetail({ match }) {
  const { request } = useApi();
  const [item, setItem] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [errorState, setErrorState] = useState('');

  const load = useCallback(async () => {
    try {
      const resp = await request('GET', `/api/cmdb/${match.params.id}/`); // eslint-disable-line react-hooks/exhaustive-deps
      setItem(resp.data);
      setLoaded(true);
    } catch {
      setErrorState('Failed to load CMDB item detail.');
    }
  }, [request, match.params.id]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

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