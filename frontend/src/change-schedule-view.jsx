/* 
 * Change Schedule View - upcoming scheduled changes view
 * Route: #/changes/schedule
 * 
 * Displays upcoming approved and scheduled changes with conflict highlighting.
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Button, DataTable, Pager, Field, Input, Select, Option, EmptyState } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError, formatDateTime, statusBadgeVariant, riskBadgeVariant, priorityBadgeVariant, STATUS_LABELS } from './changes-utils';

export function ChangeScheduleView() {
  const { isStaff } = useAuth();
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrev, setHasPrev] = useState(false);
  const [count, setCount] = useState(null);
  
  // Filters
  const [filters, setFilters] = useState({
    status: '',
    priority: '',
    risk: '',
    date_from: '',
    date_to: '',
    search: '',
  });

  useEffect(() => {
    if (!isStaff) {
      setChanges([]); // eslint-disable-line react/set-state-in-effect
      setLoading(false); // eslint-disable-line react/set-state-in-effect
      return;
    }
    
    const params = new URLSearchParams();
    params.set('page', page);
    params.set('page_size', pageSize); // eslint-disable-line react-hooks/exhaustive-deps
    if (filters.status) params.set('status', filters.status);
    if (filters.priority) params.set('priority', filters.priority);
    if (filters.risk) params.set('risk', filters.risk);
    if (filters.date_from) params.set('date_from', filters.date_from);
    if (filters.date_to) params.set('date_to', filters.date_to);
    if (filters.search) params.set('search', filters.search);
    
    fetchPage(`/changes/?${params.toString()}`)
      .then((data) => {
        setChanges(data.results || []);
        setCount(data.count || 0);
        setHasNext(Boolean(data.next));
        setHasPrev(Boolean(data.previous));
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [page, filters, pageSize, isStaff]);

  const updateFilter = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setPage(1);
  };

  const columns = [
    {
      key: 'change_number',
      label: 'Change',
      render: (row) => (
        <a href={`#/changes/${row.id}`} className="row-title">
          {row.change_number}
        </a>
      ),
    },
    {
      key: 'title',
      label: 'Title',
      render: (row) => <small className="text-muted">{row.title}</small>,
    },
    {
      key: 'status',
      label: 'Status',
      render: (row) => <Badge kind={statusBadgeVariant(row.status)}>{STATUS_LABELS[row.status] || row.status}</Badge>,
    },
    {
      key: 'risk_level',
      label: 'Risk',
      render: (row) => <Badge kind={riskBadgeVariant(row.risk_level)}>{row.risk_level || '—'}</Badge>,
    },
    {
      key: 'priority',
      label: 'Priority',
      render: (row) => <Badge kind={priorityBadgeVariant(row.priority)}>{row.priority || '—'}</Badge>,
    },
    {
      key: 'change_type',
      label: 'Type',
      render: (row) => <Badge kind="secondary">{row.change_type}</Badge>,
    },
    {
      key: 'planned_start',
      label: 'Planned Start',
      render: (row) => formatDateTime(row.planned_start),
    },
    {
      key: 'planned_end',
      label: 'Planned End',
      render: (row) => formatDateTime(row.planned_end),
    },
    {
      key: 'department',
      label: 'Department',
      render: (row) => row.department || '—',
    },
    {
      key: 'actions',
      label: '',
      thClass: 'text-right',
      render: (row) => (
        <Button kind="ghost" size="small" onClick={() => window.location.hash = `/changes/${row.id}`}>
          View
        </Button>
      ),
    },
  ];

  if (!isStaff) {
    return (
      <div>
        <PageHeader title="Schedule" />
        <EmptyState title="Access Denied" hint="Only IT staff can view the schedule." />
      </div>
    );
  }

  if (loading) {
    return <div className="mt-3"><p>Loading schedule...</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader 
        title="Change Schedule" 
        sub={count != null ? `${count} scheduled changes` : undefined}
        actions={
          <Button kind="primary" href="#/changes/new">
            New Change
          </Button>
        }
      />
      
      {/* Filters */}
      <div className="panel panel-default mt-3">
        <div className="panel-body">
          <div className="row">
            <div className="col-sm-3">
              <Field label="Status">
                <Select value={filters.status} onChange={(e) => updateFilter('status', e.target.value)}>
                  <Option value="">All Statuses</Option>
                  <Option value="approved">Approved</Option>
                  <Option value="scheduled">Scheduled</Option>
                  <Option value="in_progress">In Progress</Option>
                  <Option value="validation">Validation</Option>
                  <Option value="on_hold">On Hold</Option>
                </Select>
              </Field>
            </div>
            <div className="col-sm-3">
              <Field label="Priority">
                <Select value={filters.priority} onChange={(e) => updateFilter('priority', e.target.value)}>
                  <Option value="">All Priorities</Option>
                  <Option value="low">Low</Option>
                  <Option value="normal">Normal</Option>
                  <Option value="high">High</Option>
                  <Option value="urgent">Urgent</Option>
                  <Option value="emergency">Emergency</Option>
                </Select>
              </Field>
            </div>
            <div className="col-sm-3">
              <Field label="Risk Level">
                <Select value={filters.risk} onChange={(e) => updateFilter('risk', e.target.value)}>
                  <Option value="">All Risk Levels</Option>
                  <Option value="low">Low</Option>
                  <Option value="medium">Medium</Option>
                  <Option value="high">High</Option>
                  <Option value="critical">Critical</Option>
                </Select>
              </Field>
            </div>
            <div className="col-sm-3">
              <Field label="Search">
                <Input
                  value={filters.search}
                  onChange={(e) => updateFilter('search', e.target.value)}
                  placeholder="Search changes..."
                />
              </Field>
            </div>
          </div>
          <div className="row">
            <div className="col-sm-3">
              <Field label="From Date">
                <Input
                  type="date"
                  value={filters.date_from}
                  onChange={(e) => updateFilter('date_from', e.target.value)}
                />
              </Field>
            </div>
            <div className="col-sm-3">
              <Field label="To Date">
                <Input
                  type="date"
                  value={filters.date_to}
                  onChange={(e) => updateFilter('date_to', e.target.value)}
                />
              </Field>
            </div>
            <div className="col-sm-3">
              <Button kind="ghost" onClick={() => setFilters({ status: '', priority: '', risk: '', date_from: '', date_to: '', search: '' })}>
                Reset Filters
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Changes Table */}
      {changes.length > 0 ? (
        <div className="panel panel-default mt-3">
          <div className="panel-body">
            <DataTable
              columns={columns}
              rows={changes}
              keyOf={(r) => r.id}
              emptyTitle="No changes found"
              emptyHint="Try adjusting the filters."
            />
          </div>
          <div className="panel-footer">
            <Pager
              count={count}
              hasNext={hasNext}
              hasPrev={hasPrev}
              busy={loading}
              pageLabel={count != null ? `Page ${page}` : ''}
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => p + 1)}
            />
          </div>
        </div>
      ) : (
        <EmptyState 
          title="No scheduled changes" 
          hint="No changes match the current filters."
        />
      )}
    </div>
  );
}
