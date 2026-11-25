import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import { Badge, Button, Input, Select, Alert, DataTable, EmptyState, PageHeader } from '../../components';
import { parseApiError } from '../../api-utils';

/** Canned Responses Management Page
 * Route: #/tickets/canned-responses
 */
export function CannedResponsesPage() {
  useAuth();
  const [responses, setResponses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [, setError] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterVisibility, setFilterVisibility] = useState('');
  const [pageSize] = useState(20);
  const [searchQuery, setSearchQuery] = useState('');
  const [creating, setCreating] = useState(false);

  const fetchResponses = async () => {
    setLoading(true);
    setError('');
    try {
      let url = '/api/canned-responses/';
      if (filterCategory) url += '?category=' + filterCategory;
      if (filterVisibility) url += (url.includes('?') ? '&' : '') + 'visibility=' + filterVisibility;
      if (searchQuery) url += (url.includes('?') ? '&' : '') + 'q=' + searchQuery;
      url += '&page=' + page + '&page_size=' + pageSize;
      const r = await api.get(url);
      setResponses(r.data.results ?? r.data ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load canned responses.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResponses(); // eslint-disable-line react/set-state-in-effect
  }, [filterCategory, filterVisibility, searchQuery, page, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isEmployee) {
    return <div className="py-4"><Alert variant="danger">Access denied. Employees cannot manage canned responses.</Alert></div>;
  }

  return (
    <div className="p-4">
      <PageHeader title="Canned Responses" subtitle="Manage shared and personal canned responses" />
      <div className="mb-4">
        <Select label="Category" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
          <option value="">All categories</option>
          <option value="general">General</option>
          <option value="technical">Technical</option>
          <option value="hardware">Hardware</option>
        </Select>
        <Select label="Visibility" value={filterVisibility} onChange={(e) => setFilterVisibility(e.target.value)}>
          <option value="">All</option>
          <option value="internal">Internal</option>
          <option value="public">Public</option>
        </Select>
        <Input placeholder="Search..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
      </div>

      {creating ? (
        <div className="mb-4">
          <PageHeader title="Create Canned Response" subtitle="Creating new canned response" />
          <textarea className="input" rows={4} placeholder="Enter canned response text..." />
          <div className="mb-2">
            <Select label="Visibility">
              <option value="internal">Internal</option>
              <option value="public">Public</option>
            </Select>
          </div>
          <Button onClick={() => setCreating(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => setCreating(false)}>Save</Button>
        </div>
      ) : (
        <div>
          {loading ? (
            <p className="page-loading">Loading canned responses...</p>
          ) : responses.length === 0 ? (
            <EmptyState icon="💬" title="No Responses" text="No canned responses found." />
          ) : (
            <DataTable
              items={responses}
              pageSize={pageSize}
              columns={[
                { key: 'name', label: 'Name', render: (r) => <strong>{r.name}</strong> },
                { key: 'visibility', label: 'Visibility', render: (r) => <Badge kind="status" value={r.visibility} /> },
                { key: 'usage_count', label: 'Uses', render: (r) => r.usage_count ?? 0 },
                { key: 'actions', label: 'Actions', render: () => (
                  <div className="row-gap">
                    <Button variant="secondary" size="small">Edit</Button>
                    <Button variant="danger" size="small">Delete</Button>
                  </div>
                ) }
              ]}
            />
          )}
        </div>
      )}

      {creating && (
        <div className="mt-4">
          <Button onClick={() => setCreating(false)}>Cancel creating</Button>
        </div>
      )}
    </div>
  );
}
