import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Badge, Button, Alert, DataTable, EmptyState, PageHeader } from './components';
import { parseApiError } from './api-utils';

export function TicketQueuesPage() {
  const { isEmployee } = useAuth();
  const [queues, setQueues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const r = await api.get('/tickets/queues/');
        if (!cancelled) setQueues(r.data.results ?? r.data ?? []);
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Failed to load queues.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [refresh]);

  if (isEmployee) {
    return <div className="py-4"><Alert variant="danger">Access denied. Employees cannot manage queues.</Alert></div>;
  }

  return (
    <div className="p-4">
      <PageHeader title="Ticket queues" subtitle="Operational queue configuration" />
      {error && <Alert variant="danger">{error}</Alert>}
      <div className="mb-3"><Button onClick={() => setRefresh((r) => r + 1)}>Refresh</Button></div>
      {loading ? (
        <p className="page-loading">Loading queues...</p>
      ) : queues.length === 0 ? (
        <EmptyState icon="📋" title="No queues" text="No queues are configured." />
      ) : (
        <DataTable
          columns={[
            { key: 'name', label: 'Queue', render: (q) => <strong>{q.name}</strong> },
            { key: 'is_active', label: 'Status', render: (q) => <Badge kind="status" value={q.is_active ? 'active' : 'inactive'}>{q.is_active ? 'Active' : 'Inactive'}</Badge> },
          ]}
          items={queues}
          pageSize={20}
          noDataText="No queues found"
        />
      )}
    </div>
  );
}
