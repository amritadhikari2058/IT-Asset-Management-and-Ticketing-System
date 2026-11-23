import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Badge, Button, Input, Select, Alert, DataTable, EmptyState, PageHeader } from './components';
import { parseApiError } from './api-utils';

/**
 * Ticket Operations Dashboard Page
 * Route: #/tickets/operations
 */
export function TicketOperationsDashboard() {
  useAuth();
  const [loading, setLoading] = useState(true);
  const [, setError] = useState('');
  const [kpiActive, setKPIActive] = useState(0);
  const [kpiUnassigned, setKPIUnassigned] = useState(0);
  const [kpiInProgress, setKPIInProgress] = useState(0);
  const [kpiWaiting, setKPIWaiting] = useState(0);
  const [kpiSLABreach, setKPISLA] = useState(0);
  const [kpiUrgent, setKPIUrgent] = useState(0);
  const [queues, setQueues] = useState([]);
  const [filterQueue, setFilterQueue] = useState('');
  const [filterDept] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const fetchData = async () => {
    setLoading(true);
    setError('');
    try {
      let url = '/api/operations/';
      if (dateFrom) url += '?date_from=' + dateFrom;
      if (dateTo) url += (url.includes('?') ? '&' : '') + 'date_to=' + dateTo;
      if (filterQueue) url += (url.includes('?') ? '&' : '') + 'queue=' + filterQueue;
      if (filterDept) url += (url.includes('?') ? '&' : '') + 'department=' + filterDept;

      const r = await api.get(url);
      setKPIActive(r.data.active_tickets ?? 0);
      setKPIUnassigned(r.data.unassigned ?? 0);
      setKPIInProgress(r.data.in_progress ?? 0);
      setKPIWaiting(r.data.waiting_requester ?? 0);
      setKPISLA(r.data.sla_breached ?? 0);
      setKPIUrgent(r.data.urgent ?? 0);
      setQueues(r.data.queues ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load operations dashboard.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(); // eslint-disable-line react/set-state-in-effect
  }, [dateFrom, dateTo, filterQueue, filterDept]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isEmployee) {
    return (
      <div className="py-4">
        <Alert variant="danger">
          Access denied. Employees cannot view operations dashboard.
        </Alert>
      </div>
    );
  }

  return (
    <div className="p-4">
      <PageHeader title="Operations Dashboard" subtitle="Service desk metrics" />

      <div className="mb-4">
        <div className="row g-3">
          <div className="col-md-3">
            <Input placeholder="From" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="col-md-3">
            <Input placeholder="To" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          <div className="col-md-2">
            <Select
              label="Queue"
              value={filterQueue}
              onChange={(e) => setFilterQueue(e.target.value)}
            >
              <option value="">All queues</option>
              {queues.map(q => (
                <option key={q.id} value={q.code || q.id}>
                  {q.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="col-md-2">
            <Button onClick={() => fetchData()}>Refresh</Button>
          </div>
        </div>
      </div>

      <div className="row mb-4">
        <div className="col-md-2">
          <Badge variant="primary">{kpiActive || 0}</Badge>
          <small>Active</small>
        </div>
        <div className="col-md-2">
          <Badge variant="secondary">{kpiUnassigned || 0}</Badge>
          <small>Unassigned</small>
        </div>
        <div className="col-md-2">
          <Badge variant="success">{kpiInProgress || 0}</Badge>
          <small>In Progress</small>
        </div>
        <div className="col-md-2">
          <Badge variant="info">{kpiWaiting || 0}</Badge>
          <small>Waiting Requester</small>
        </div>
      </div>

      <div className="row mb-4">
        <div className="col-md-2">
          <Badge variant="danger">{kpiSLABreach || 0}</Badge>
          <small>SLA Breached</small>
        </div>
        <div className="col-md-2">
          <Badge variant="warning">{kpiUrgent || 0}</Badge>
          <small>Urgent</small>
        </div>
      </div>

      {loading ? (
        <p className="page-loading">Loading operations dashboard...</p>
      ) : kpiActive === 0 ? (
        <EmptyState icon="📊" title="No Data" text="Dashboard data will appear here." />
      ) : (
        <DataTable
          columns={[
            { key: 'name', label: 'Queue', render: (q) => <strong>{q.name}</strong> },
            { key: 'ticket_count', label: 'Tickets', render: (q) => q.ticket_count ?? 0 },
            { key: 'is_active', label: 'Status', render: (q) => (
              <Badge kind="status" value={q.is_active ? 'active' : 'inactive'}>
                {q.is_active ? 'Active' : 'Inactive'}
              </Badge>
            ) },
          ]}
          items={queues}
          pageSize={20}
          noDataText="No queues found"
        />
      )}
    </div>
  );
}