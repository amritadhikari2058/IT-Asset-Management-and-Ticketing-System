import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Button, Input, Select, Alert, DataTable, EmptyState, PageHeader } from './components';
import { parseApiError } from './api-utils';

/** Ticket Templates Management Page
 * Route: #/tickets/templates
 */
export function TicketTemplatesPage() {
  useAuth();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [, setError] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);
  const [page] = useState(1);
  const [pageSize] = useState(20);
  const [searchQuery, setSearchQuery] = useState('');
  const [creating, setCreating] = useState(false);

  const fetchTemplates = async () => {
    setLoading(true);
    setError('');
    try {
      let url = '/api/templates/';
      if (filterCategory) url += '?category=' + filterCategory;
      if (activeOnly) url += (url.includes('?') ? '&' : '') + 'is_active=true';
      if (searchQuery) url += (url.includes('?') ? '&' : '') + 'q=' + searchQuery;
      url += '&page=' + page + '&page_size=' + pageSize;
      const r = await api.get(url);
      setTemplates(r.data.results ?? r.data ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load templates.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates(); // eslint-disable-line react/set-state-in-effect
  }, [filterCategory, activeOnly, searchQuery, page, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isEmployee) {
    return <div className="py-4"><Alert variant="danger">Employees cannot manage ticket templates.</Alert></div>;
  }

  return (
    <div className="p-4">
      <PageHeader title="Ticket Templates" subtitle="Manage shared and personal templates" />
      <div className="mb-4">
        <Select label="Category" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
          <option value="">All categories</option>
          <option value="general">General</option>
          <option value="hardware">Hardware</option>
          <option value="software">Software</option>
        </Select>
        <Select label="Active only" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)}>
          <option value="true">Active only</option>
          <option value="false">All</option>
        </Select>
        <Input placeholder="Search..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
      </div>

      {creating ? (
        <div className="mb-4">
          <PageHeader title="Create Template" subtitle="Creating new ticket template" />
          <div className="row g-3">
            <Input placeholder="Template name" />
            <Input placeholder="Description" rows={2} />
          </div>
          <Button onClick={() => setCreating(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => setCreating(false)}>Save</Button>
        </div>
      ) : (
        <div>
          {loading ? (
            <p className="page-loading">Loading templates...</p>
          ) : templates.length === 0 ? (
            <EmptyState icon="📋" title="No Templates" text="No ticket templates found." />
          ) : (
            <DataTable
              items={templates}
              pageSize={pageSize}
              columns={[
                { key: 'name', label: 'Name', render: (t) => <strong>{t.name}</strong> },
                { key: 'category', label: 'Category', render: (t) => t.category_name ?? '-' },
                { key: 'usage_count', label: 'Uses', render: (t) => t.usage_count ?? 0 },
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