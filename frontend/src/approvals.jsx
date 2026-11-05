import { useCallback, useEffect, useState } from 'react';
import { useAuth } from './auth';
import api from './api';
import { DataTable, Badge, EmptyState, PageHeader, Button } from './components';

function rowFor(item) {
  const typeLabel = {
    service_request: 'Service Request',
    disposal: 'Disposal',
    purchase_request: 'Purchase Request',
    purchase_order: 'Purchase Order',
    workflow_approval: 'Workflow Approval',
    knowledge_base: 'KB Review',
  }[item.type] || item.type;

  return {
    id: item.id,
    type: typeLabel,
    reference: item.reference,
    title: item.title,
    requester: item.requester,
    age: item.age_hours,
    actions: item.actions,
  };
}

export function ApprovalCenter() {
  const { isStaff } = useAuth();
  const [approvals, setApprovals] = useState([]);
  const [counts, setCounts] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [listRes, countsRes] = await Promise.all([
        api.get('/api/approvals/'),
        api.get('/api/approvals/counts/'),
      ]);
      setApprovals(listRes.data.approvals.map(rowFor));
      setCounts(countsRes.data);
    } catch (e) {
      setError('Could not load pending approvals.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isStaff) return;
    let active = true;
    load().finally(() => { active = false; });
  }, [isStaff, load]);

  if (!isStaff) return <EmptyState title="Approvals" hint="Only staff can access approvals." />;
  if (loading) return <div className="panel-pad"><div className="muted">Loading approvals…</div></div>;
  if (error) return <div className="error-summary" role="alert">{error}</div>;

  const totalPending = counts?.total ?? 0;

  return (
    <div>
      <PageHeader
        title="Approvals"
        sub={`${totalPending} pending approval${totalPending !== 1 ? 's' : ''}`}
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            {counts && counts.service_request > 0 && <Badge label={`${counts.service_request} SR`} kind="pending" />}
            {counts && counts.disposal > 0 && <Badge label={`${counts.disposal} Disp`} kind="pending" />}
            {counts && counts.purchase_request > 0 && <Badge label={`${counts.purchase_request} PR`} kind="pending" />}
            {counts && counts.purchase_order > 0 && <Badge label={`${counts.purchase_order} PO`} kind="pending" />}
            {counts && counts.workflow_approval > 0 && <Badge label={`${counts.workflow_approval} WF`} kind="pending" />}
            {counts && counts.knowledge_base > 0 && <Badge label={`${counts.knowledge_base} KB`} kind="pending" />}
          </div>
        }
      />
      {approvals.length === 0 ? (
        <EmptyState title="No pending approvals" hint="Nothing waiting for your decision right now." />
      ) : (
        <DataTable
          columns={[
            { key: 'type', label: 'Type' },
            { key: 'reference', label: 'Reference' },
            { key: 'title', label: 'Title' },
            { key: 'requester', label: 'Requested by' },
            { key: 'age', label: 'Age (hrs)', render: (v) => v.toFixed(1) },
            {
              key: 'actions',
              label: 'Actions',
              render: (_, r) => (
                <div style={{ display: 'flex', gap: 6 }}>
                  {r.actions?.includes('approve') && (
                    <Button kind="primary" size="small">Approve</Button>
                  )}
                  {r.actions?.includes('reject') && (
                    <Button kind="danger" size="small">Reject</Button>
                  )}
                  {r.actions?.includes('return_for_correction') && (
                    <Button kind="ghost" size="small">Return</Button>
                  )}
                </div>
              ),
            },
          ]}
          rows={approvals}
          keyOf={(r) => r.id}
          emptyTitle="No approvals"
          emptyHint="Nothing waiting."
        />
      )}
    </div>
  );
}
