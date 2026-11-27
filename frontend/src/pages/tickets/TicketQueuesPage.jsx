import { useCallback, useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Alert,
  Badge,
  Button,
  CategorySelect,
  ConfirmDialog,
  DataTable,
  DepartmentSelect,
  EmptyState,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  UserSelect,
} from '../../components';
import { parseApiError } from '../../api-utils';

const EMPTY_FORM = {
  name: '',
  code: '',
  description: '',
  department: '',
  default_category: '',
  default_priority: '',
  email_address: '',
  assignment_strategy: 'manual',
  allow_self_claim: true,
  manager: '',
};

const STRATEGY_OPTIONS = [
  ['manual', 'Manual'],
  ['round_robin', 'Round Robin'],
  ['least_open_tickets', 'Least Open Tickets'],
  ['category_owner', 'Category Owner'],
  ['department_queue', 'Department Queue'],
];

function toForm(queue) {
  return {
    name: queue.name ?? '',
    code: queue.code ?? '',
    description: queue.description ?? '',
    department: queue.department ?? '',
    default_category: queue.default_category ?? '',
    default_priority: queue.default_priority ?? '',
    email_address: queue.email_address ?? '',
    assignment_strategy: queue.assignment_strategy || 'manual',
    allow_self_claim: Boolean(queue.allow_self_claim),
    manager: queue.manager ?? '',
  };
}

function normalizeList(data) {
  if (Array.isArray(data?.results)) return data.results;
  return Array.isArray(data) ? data : [];
}

export function TicketQueuesPage() {
  const { isStaff, isManagerOrAdmin } = useAuth();

  const [queues, setQueues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deactivating, setDeactivating] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [formError, setFormError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [deactivateTarget, setDeactivateTarget] = useState(null);
  const [selectedQueue, setSelectedQueue] = useState(null);
  const [queueDetails, setQueueDetails] = useState(null);
  const [queueTickets, setQueueTickets] = useState([]);
  const [queueMemberships, setQueueMemberships] = useState([]);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState('');
  const [membershipError, setMembershipError] = useState('');
  const [membershipFormOpen, setMembershipFormOpen] = useState(false);
  const [editingMembership, setEditingMembership] = useState(null);
  const [membershipSaving, setMembershipSaving] = useState(false);
  const [membershipRemoveTarget, setMembershipRemoveTarget] = useState(null);
  const [membershipRemoving, setMembershipRemoving] = useState(false);
  const [autoAssignTarget, setAutoAssignTarget] = useState(null);
  const [autoAssigning, setAutoAssigning] = useState(false);
  const [membershipForm, setMembershipForm] = useState({
    user: '',
    role: 'agent',
    can_claim: true,
    can_assign_others: false,
    can_view_all: false,
  });

  const loadQueues = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get('/tickets/queues/');
      setQueues(normalizeList(response.data));
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load ticket queues.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isStaff) loadQueues();
  }, [isStaff, loadQueues, refresh]);

  const updateField = (name, value) => {
    setForm((current) => ({ ...current, [name]: value }));
  };

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM });
    setFormError('');
    setNotice('');
    setFormOpen(true);
  };

  const openEdit = (queue) => {
    if (!isManagerOrAdmin) return;
    setEditing(queue);
    setForm(toForm(queue));
    setFormError('');
    setNotice('');
    setFormOpen(true);
  };

  const closeForm = () => {
    if (saving) return;
    setFormOpen(false);
    setEditing(null);
    setFormError('');
  };

  const submitForm = async (event) => {
    event.preventDefault();
    if (saving || !isManagerOrAdmin) return;

    setFormError('');
    if (!form.name.trim()) {
      setFormError('Queue name is required.');
      return;
    }
    if (!form.code.trim()) {
      setFormError('Queue code is required.');
      return;
    }

    const payload = {
      name: form.name.trim(),
      code: form.code.trim().toUpperCase(),
      description: form.description,
      department: form.department || null,
      default_category: form.default_category || null,
      default_priority: form.default_priority,
      email_address: form.email_address.trim(),
      assignment_strategy: form.assignment_strategy,
      allow_self_claim: Boolean(form.allow_self_claim),
      manager: form.manager || null,
    };

    setSaving(true);
    setError('');
    try {
      if (editing) {
        await api.put(`/tickets/queues/${editing.id}/`, payload);
      } else {
        await api.post('/tickets/queues/', payload);
      }

      setFormOpen(false);
      setEditing(null);
      setNotice(editing ? 'Queue updated successfully.' : 'Queue created successfully.');
      setRefresh((value) => value + 1);
    } catch (e) {
      setFormError(parseApiError(e).global || 'Could not save the queue.');
    } finally {
      setSaving(false);
    }
  };

  const confirmDeactivate = async () => {
    if (!deactivateTarget || deactivating || !isManagerOrAdmin) return;

    setDeactivating(true);
    setError('');
    setNotice('');
    try {
      await api.post(`/tickets/queues/${deactivateTarget.id}/deactivate/`);
      setNotice(`Queue "${deactivateTarget.name}" was deactivated.`);
      setDeactivateTarget(null);
      setRefresh((value) => value + 1);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not deactivate the queue.');
    } finally {
      setDeactivating(false);
    }
  };

  const openQueueDetails = async (queue) => {
    setSelectedQueue(queue);
    setQueueDetails(null);
    setQueueTickets([]);
    setQueueMemberships([]);
    setDetailsError('');
    setMembershipError('');
    setMembershipFormOpen(false);
    setEditingMembership(null);
    setMembershipRemoveTarget(null);
    setDetailsLoading(true);

    try {
      const [ticketsResponse, metricsResponse] = await Promise.all([
        api.get(`/tickets/queues/${queue.id}/tickets/`),
        api.get(`/tickets/queues/${queue.id}/metrics/`),
      ]);

      setQueueTickets(normalizeList(ticketsResponse.data));
      setQueueDetails(metricsResponse.data || {});

      if (isManagerOrAdmin) {
        try {
          const membershipsResponse = await api.get(
            `/tickets/queue-memberships/?queue=${queue.id}`
          );
          setQueueMemberships(normalizeList(membershipsResponse.data));
        } catch (membershipLoadError) {
          setMembershipError(
            parseApiError(membershipLoadError).global
              || 'Could not load queue memberships.'
          );
        }
      }
    } catch (e) {
      setDetailsError(
        parseApiError(e).global || 'Could not load queue details.'
      );
    } finally {
      setDetailsLoading(false);
    }
  };

  const saveQueueMember = async (event) => {
    event.preventDefault();

    if (!selectedQueue || !isManagerOrAdmin || membershipSaving) return;

    const isEditing = Boolean(editingMembership);

    if (!isEditing && !membershipForm.user) {
      setMembershipError('Select an IT staff member first.');
      return;
    }

    const isObserver = membershipForm.role === 'observer';
    const permissions = {
      role: membershipForm.role,
      can_claim: isObserver ? false : Boolean(membershipForm.can_claim),
      can_assign_others: isObserver
        ? false
        : Boolean(membershipForm.can_assign_others),
      can_view_all: Boolean(membershipForm.can_view_all),
    };

    const payload = isEditing
      ? permissions
      : {
          queue: selectedQueue.id,
          user: Number(membershipForm.user),
          ...permissions,
        };

    setMembershipSaving(true);
    setMembershipError('');
    setNotice('');

    try {
      if (isEditing) {
        await api.put(
          `/tickets/queue-memberships/${editingMembership.id}/`,
          payload
        );
      } else {
        await api.post('/tickets/queue-memberships/', payload);
      }

      setMembershipFormOpen(false);
      setEditingMembership(null);
      setMembershipForm({
        user: '',
        role: 'agent',
        can_claim: true,
        can_assign_others: false,
        can_view_all: false,
      });
      setNotice(
        isEditing
          ? 'Queue member updated successfully.'
          : 'Queue member added successfully.'
      );

      try {
        const response = await api.get(
          `/tickets/queue-memberships/?queue=${selectedQueue.id}`
        );
        setQueueMemberships(normalizeList(response.data));
      } catch (refreshError) {
        setMembershipError(
          isEditing
            ? 'Member was updated, but the membership list could not be refreshed. Reopen the queue details to reload it.'
            : 'Member was added, but the membership list could not be refreshed. Reopen the queue details to reload it.'
        );
      }
    } catch (e) {
      setMembershipError(
        parseApiError(e).global
          || (isEditing
            ? 'Could not update the queue member.'
            : 'Could not add the queue member.')
      );
    } finally {
      setMembershipSaving(false);
    }
  };

  const confirmRemoveQueueMember = async () => {
    if (
      !membershipRemoveTarget
      || !selectedQueue
      || !isManagerOrAdmin
      || membershipRemoving
    ) return;

    const target = membershipRemoveTarget;
    const memberLabel = target.user_email || `User #${target.user}`;

    setMembershipRemoving(true);
    setMembershipError('');
    setNotice('');

    try {
      await api.post(`/tickets/queue-memberships/${target.id}/remove/`);

      setMembershipRemoveTarget(null);
      setNotice(`${memberLabel} was removed from the queue.`);

      try {
        const response = await api.get(
          `/tickets/queue-memberships/?queue=${selectedQueue.id}`
        );
        setQueueMemberships(normalizeList(response.data));
      } catch (refreshError) {
        setMembershipError(
          'Member was removed, but the membership list could not be refreshed. Reopen the queue details to reload it.'
        );
      }
    } catch (e) {
      setMembershipRemoveTarget(null);
      setMembershipError(
        parseApiError(e).global || 'Could not remove the queue member.'
      );
    } finally {
      setMembershipRemoving(false);
    }
  };

  const confirmAutoAssign = async () => {
    if (!autoAssignTarget || !isManagerOrAdmin || autoAssigning) return;

    const target = autoAssignTarget;
    setAutoAssigning(true);
    setError('');
    setNotice('');

    try {
      const response = await api.post(
        `/tickets/queues/${target.id}/auto-assign/`
      );

      const assigned = Array.isArray(response.data?.assigned)
        ? response.data.assigned
        : [];

      setAutoAssignTarget(null);
      setNotice(
        assigned.length
          ? `${assigned.length} unassigned ticket(s) were assigned in "${target.name}".`
          : `No unassigned open tickets needed assignment in "${target.name}".`
      );

      try {
        const [ticketsResponse, metricsResponse] = await Promise.all([
          api.get(`/tickets/queues/${target.id}/tickets/`),
          api.get(`/tickets/queues/${target.id}/metrics/`),
        ]);

        if (selectedQueue?.id === target.id) {
          setQueueTickets(normalizeList(ticketsResponse.data));
          setQueueDetails(metricsResponse.data || {});
        }
      } catch (refreshError) {
        setError(
          'Tickets were assigned, but queue details could not be refreshed. Close and reopen the queue to reload them.'
        );
      }
    } catch (e) {
      setAutoAssignTarget(null);
      setError(
        parseApiError(e).global || 'Could not auto-assign queue tickets.'
      );
    } finally {
      setAutoAssigning(false);
    }
  };

  const openEditMembership = (membership) => {
    if (!isManagerOrAdmin || membershipSaving) return;

    setMembershipError('');
    setEditingMembership(membership);
    setMembershipForm({
      user: membership.user ?? '',
      role: membership.role || 'agent',
      can_claim: Boolean(membership.can_claim),
      can_assign_others: Boolean(membership.can_assign_others),
      can_view_all: Boolean(membership.can_view_all),
    });
    setMembershipFormOpen(true);
  };

  if (!isStaff) {
    return (
      <div className="p-4">
        <Alert variant="danger">Access denied. Ticket queues are available to IT staff only.</Alert>
      </div>
    );
  }

  const columns = [
    {
      key: 'view',
      label: 'Details',
      render: (queue) => (
        <Button
          kind="secondary"
          size="small"
          onClick={() => openQueueDetails(queue)}
        >
          View
        </Button>
      ),
    },
    {
      key: 'name',
      label: 'Queue',
      render: (queue) => (
        <div>
          <strong>{queue.name}</strong>
          <div className="muted small">{queue.code}</div>
          {queue.description ? (
            <div className="muted small">{queue.description}</div>
          ) : null}
        </div>
      ),
    },
    {
      key: 'department_name',
      label: 'Department',
      render: (queue) => queue.department_name || 'All departments',
    },
    {
      key: 'ticket_count',
      label: 'Tickets',
      render: (queue) => queue.ticket_count ?? 0,
    },
    {
      key: 'default_priority',
      label: 'Default priority',
      render: (queue) => queue.default_priority || 'Not set',
    },
    {
      key: 'assignment_strategy',
      label: 'Assignment',
      render: (queue) => (
        STRATEGY_OPTIONS.find(([value]) => value === queue.assignment_strategy)?.[1]
        || queue.assignment_strategy
        || 'Manual'
      ),
    },
    {
      key: 'manager_email',
      label: 'Queue manager',
      render: (queue) => queue.manager_email || 'Not assigned',
    },
    {
      key: 'is_active',
      label: 'Status',
      render: (queue) => (
        <Badge kind="status" value={queue.is_active ? 'active' : 'inactive'}>
          {queue.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    ...(isManagerOrAdmin
      ? [{
          key: 'actions',
          label: 'Actions',
          render: (queue) => (
            <div className="row-gap">
              <Button kind="secondary" size="small" onClick={() => openEdit(queue)}>
                Edit
              </Button>
              {queue.is_active ? (
                <Button
                  kind="danger"
                  size="small"
                  onClick={() => setDeactivateTarget(queue)}
                >
                  Deactivate
                </Button>
              ) : null}
            </div>
          ),
        }]
      : []),
  ];

  return (
    <div className="p-4">
      <PageHeader
        title="Ticket queues"
        sub="Operational queue configuration"
        actions={
          <div className="row-gap">
            {isManagerOrAdmin ? (
              <Button onClick={openCreate}>Create queue</Button>
            ) : null}
            <Button kind="secondary" onClick={() => setRefresh((value) => value + 1)}>
              Refresh
            </Button>
          </div>
        }
      />

      {error ? <Alert variant="danger">{error}</Alert> : null}
      {notice ? <Alert variant="success">{notice}</Alert> : null}

      {selectedQueue ? (
        <section className="card p-3 mb-4">
          <div className="d-flex justify-content-between align-items-center gap-2 mb-3">
            <div>
              <h2 className="h5 mb-1">{selectedQueue.name} — Workload</h2>
              <div className="muted small">
                Queue code: {selectedQueue.code}
              </div>
            </div>
            <Button
              kind="secondary"
              size="small"
              onClick={() => {
                setSelectedQueue(null);
                setQueueDetails(null);
                setQueueTickets([]);
                setQueueMemberships([]);
                setDetailsError('');
                setMembershipError('');
                setMembershipFormOpen(false);
                setEditingMembership(null);
                setMembershipRemoveTarget(null);
              }}
            >
              Close details
            </Button>
          </div>

          {detailsError ? (
            <Alert variant="danger">{detailsError}</Alert>
          ) : null}

          {detailsLoading ? (
            <p className="page-loading">Loading queue workload and tickets...</p>
          ) : null}

          {!detailsLoading && !detailsError && queueDetails ? (
            <>
              <div className="d-flex justify-content-between align-items-center gap-2 mb-3">
                <h3 className="h6 mb-0">Queue metrics</h3>
                {isManagerOrAdmin
                  && ['manual', 'least_open_tickets', 'round_robin'].includes(
                    selectedQueue?.assignment_strategy
                  ) ? (
                    <Button
                      size="small"
                      kind="secondary"
                      disabled={autoAssigning}
                      onClick={() => setAutoAssignTarget(selectedQueue)}
                    >
                      Auto-assign unassigned tickets
                    </Button>
                  ) : null}
              </div>

              <div className="row g-2 mb-4">
                {[
                  ['Active tickets', queueDetails.total_active],
                  ['Unassigned', queueDetails.unassigned],
                  ['Assigned', queueDetails.assigned],
                  ['In progress', queueDetails.in_progress],
                  ['Waiting requester', queueDetails.waiting_requester],
                  ['Waiting third party', queueDetails.waiting_third_party],
                  ['Overdue', queueDetails.overdue],
                  ['SLA breached', queueDetails.sla_breached],
                  ['Urgent', queueDetails.urgent],
                  ['Queue members', queueDetails.members],
                  [
                    'Oldest ticket age (days)',
                    queueDetails.oldest_ticket_age_days ?? '—',
                  ],
                ].map(([label, value]) => (
                  <div className="col-6 col-md-3" key={label}>
                    <div className="border rounded p-3 h-100">
                      <div className="muted small">{label}</div>
                      <strong>{value ?? 0}</strong>
                    </div>
                  </div>
                ))}
              </div>

              <h3 className="h6 mb-2">Member workload</h3>

              <DataTable
                columns={[
                  {
                    key: 'user_name',
                    label: 'Member',
                    render: (member) => member.user_name || `User #${member.user}`,
                  },
                  {
                    key: 'role',
                    label: 'Queue role',
                    render: (member) => member.role || '—',
                  },
                  {
                    key: 'assigned_active',
                    label: 'Assigned active tickets',
                    render: (member) => member.assigned_active ?? 0,
                  },
                ]}
                rows={queueDetails.workload_by_member || []}
                keyOf={(member) => member.user}
                emptyTitle="No active queue members"
                emptyHint="Membership workload will appear here when members are added."
              />

              {isManagerOrAdmin ? (
                <>
                  <div className="d-flex justify-content-between align-items-center gap-2 mt-4 mb-2">
                    <h3 className="h6 mb-0">Queue membership</h3>
                    <Button
                      size="small"
                      onClick={() => {
                        setMembershipError('');
                        setEditingMembership(null);
                        setMembershipForm({
                          user: '',
                          role: 'agent',
                          can_claim: true,
                          can_assign_others: false,
                          can_view_all: false,
                        });
                        setMembershipFormOpen((open) => !open);
                      }}
                    >
                      {membershipFormOpen ? 'Cancel' : 'Add member'}
                    </Button>
                  </div>

                  {membershipError ? (
                    <Alert variant="danger">{membershipError}</Alert>
                  ) : null}

                  {membershipFormOpen ? (
                    <form className="border rounded p-3 mb-3" onSubmit={saveQueueMember}>
                      <h4 className="h6 mb-3">
                        {editingMembership ? 'Edit queue member' : 'Add queue member'}
                      </h4>
                      <div className="row g-3">
                        {!editingMembership ? (
                          <div className="col-md-6">
                            <Field label="IT staff member">
                              <UserSelect
                                value={membershipForm.user}
                                onChange={(value) => setMembershipForm((current) => ({
                                  ...current,
                                  user: value,
                                }))}
                                disabled={membershipSaving}
                                label="Queue member"
                              />
                            </Field>
                          </div>
                        ) : null}

                        <div className="col-md-6">
                          <Select
                            label="Queue role"
                            value={membershipForm.role}
                            onChange={(event) => {
                              const role = event.target.value;
                              setMembershipForm((current) => ({
                                ...current,
                                role,
                                ...(role === 'observer'
                                  ? { can_claim: false, can_assign_others: false }
                                  : {}),
                              }));
                            }}
                            disabled={membershipSaving}
                          >
                            <option value="manager">Queue Manager</option>
                            <option value="agent">Agent</option>
                            <option value="observer">Observer</option>
                          </Select>
                        </div>

                        <div className="col-12">
                          <div className="d-flex flex-wrap gap-3">
                            <label className="form-check">
                              <input
                                className="form-check-input"
                                type="checkbox"
                                checked={membershipForm.can_claim}
                                onChange={(event) => setMembershipForm((current) => ({
                                  ...current,
                                  can_claim: event.target.checked,
                                }))}
                                disabled={membershipSaving || membershipForm.role === 'observer'}
                              />
                              <span className="form-check-label">Can claim tickets</span>
                            </label>

                            <label className="form-check">
                              <input
                                className="form-check-input"
                                type="checkbox"
                                checked={membershipForm.can_assign_others}
                                onChange={(event) => setMembershipForm((current) => ({
                                  ...current,
                                  can_assign_others: event.target.checked,
                                }))}
                                disabled={membershipSaving || membershipForm.role === 'observer'}
                              />
                              <span className="form-check-label">Can assign tickets to others</span>
                            </label>

                            <label className="form-check">
                              <input
                                className="form-check-input"
                                type="checkbox"
                                checked={membershipForm.can_view_all}
                                onChange={(event) => setMembershipForm((current) => ({
                                  ...current,
                                  can_view_all: event.target.checked,
                                }))}
                                disabled={membershipSaving}
                              />
                              <span className="form-check-label">Can view all queue tickets</span>
                            </label>
                          </div>
                          {membershipForm.role === 'observer' ? (
                            <p className="muted small mt-2 mb-0">
                              Observers cannot claim tickets or assign tickets to others.
                            </p>
                          ) : null}
                        </div>
                      </div>

                      <div className="row-gap mt-3">
                        <Button
                          type="submit"
                          disabled={membershipSaving || (!editingMembership && !membershipForm.user)}
                        >
                          {membershipSaving
                            ? (editingMembership ? 'Saving changes...' : 'Adding member...')
                            : (editingMembership ? 'Save changes' : 'Add member')}
                        </Button>
                        <Button
                          kind="secondary"
                          onClick={() => {
                            if (!membershipSaving) {
                              setMembershipFormOpen(false);
                              setEditingMembership(null);
                            }
                          }}
                          disabled={membershipSaving}
                        >
                          Cancel
                        </Button>
                      </div>
                    </form>
                  ) : null}

                  <DataTable
                    columns={[
                      {
                        key: 'user_email',
                        label: 'Member',
                        render: (membership) => membership.user_email || `User #${membership.user}`,
                      },
                      {
                        key: 'role',
                        label: 'Role',
                        render: (membership) => membership.role || '—',
                      },
                      {
                        key: 'is_active',
                        label: 'Status',
                        render: (membership) => membership.is_active ? 'Active' : 'Inactive',
                      },
                      {
                        key: 'can_claim',
                        label: 'Can claim',
                        render: (membership) => membership.can_claim ? 'Yes' : 'No',
                      },
                      {
                        key: 'can_assign_others',
                        label: 'Can assign others',
                        render: (membership) => membership.can_assign_others ? 'Yes' : 'No',
                      },
                      {
                        key: 'can_view_all',
                        label: 'Can view all',
                        render: (membership) => membership.can_view_all ? 'Yes' : 'No',
                      },
                      {
                        key: 'actions',
                        label: 'Actions',
                        render: (membership) => (
                          <div className="row-gap">
                            <Button
                              kind="secondary"
                              size="small"
                              disabled={!membership.is_active || membershipSaving || membershipRemoving}
                              onClick={() => openEditMembership(membership)}
                            >
                              Edit
                            </Button>
                            {membership.is_active ? (
                              <Button
                                kind="danger"
                                size="small"
                                disabled={membershipSaving || membershipRemoving}
                                onClick={() => {
                                  setMembershipError('');
                                  setMembershipFormOpen(false);
                                  setEditingMembership(null);
                                  setMembershipRemoveTarget(membership);
                                }}
                              >
                                Remove
                              </Button>
                            ) : null}
                          </div>
                        ),
                      },
                    ]}
                    rows={queueMemberships}
                    keyOf={(membership) => membership.id}
                    emptyTitle="No queue members configured"
                    emptyHint="Add eligible IT staff to this queue to manage its membership."
                  />
                </>
              ) : null}

              <h3 className="h6 mt-4 mb-2">Queue tickets</h3>

              <DataTable
                columns={[
                  {
                    key: 'title',
                    label: 'Ticket',
                    render: (ticket) => (
                      <a className="row-title" href={`#/tickets/${ticket.id}`}>
                        {ticket.title || `Ticket #${ticket.id}`}
                      </a>
                    ),
                  },
                  {
                    key: 'status',
                    label: 'Status',
                    render: (ticket) => (
                      <Badge kind="status" value={ticket.status}>
                        {ticket.status}
                      </Badge>
                    ),
                  },
                  {
                    key: 'priority',
                    label: 'Priority',
                    render: (ticket) => (
                      <Badge kind="priority" value={ticket.priority}>
                        {ticket.priority}
                      </Badge>
                    ),
                  },
                  {
                    key: 'requester_email',
                    label: 'Requester',
                    render: (ticket) => ticket.requester_email || '—',
                  },
                  {
                    key: 'assignee_email',
                    label: 'Assignee',
                    render: (ticket) => ticket.assignee_email || 'Unassigned',
                  },
                  {
                    key: 'sla',
                    label: 'SLA',
                    render: (ticket) => (
                      ticket.is_overdue
                        ? <Badge kind="status" value="overdue">Overdue</Badge>
                        : ticket.sla_breached
                          ? <Badge kind="status" value="overdue">Breached</Badge>
                          : ticket.sla_due_at
                            ? new Date(ticket.sla_due_at).toLocaleString()
                            : '—'
                    ),
                  },
                  {
                    key: 'created_at',
                    label: 'Created',
                    render: (ticket) => (
                      ticket.created_at
                        ? new Date(ticket.created_at).toLocaleString()
                        : '—'
                    ),
                  },
                ]}
                rows={queueTickets}
                keyOf={(ticket) => ticket.id}
                emptyTitle="No tickets in this queue"
                emptyHint="Tickets assigned to this queue will appear here."
              />
            </>
          ) : null}
        </section>
      ) : null}

      {loading ? (
        <p className="page-loading">Loading queues...</p>
      ) : queues.length === 0 ? (
        <EmptyState
          title="No queues configured"
          hint={
            isManagerOrAdmin
              ? 'Create a queue to organize and route support tickets.'
              : 'There are currently no active ticket queues.'
          }
          action={
            isManagerOrAdmin
              ? <Button onClick={openCreate}>Create queue</Button>
              : null
          }
        />
      ) : (
        <DataTable
          columns={columns}
          rows={queues}
          keyOf={(queue) => queue.id}
          emptyTitle="No queues found"
          emptyHint="No active ticket queues are configured."
        />
      )}

      {formOpen ? (
        <Modal
          title={editing ? 'Edit ticket queue' : 'Create ticket queue'}
          onClose={closeForm}
          size="large"
        >
          {formError ? <Alert variant="danger">{formError}</Alert> : null}

          <form onSubmit={submitForm}>
            <div className="row g-3">
              <div className="col-md-6">
                <Input
                  label="Queue name"
                  value={form.name}
                  onChange={(event) => updateField('name', event.target.value)}
                  required
                  disabled={saving}
                />
              </div>
              <div className="col-md-6">
                <Input
                  label="Queue code"
                  value={form.code}
                  onChange={(event) => updateField('code', event.target.value)}
                  required
                  disabled={saving}
                />
              </div>
              <div className="col-12">
                <Input
                  label="Description"
                  rows={3}
                  value={form.description}
                  onChange={(event) => updateField('description', event.target.value)}
                  disabled={saving}
                />
              </div>
              <div className="col-md-6">
                <Field label="Department">
                  <DepartmentSelect
                    value={form.department}
                    onChange={(value) => updateField('department', value)}
                    disabled={saving}
                  />
                </Field>
              </div>
              <div className="col-md-6">
                <Field label="Default ticket category">
                  <CategorySelect
                    kind="ticket"
                    value={form.default_category}
                    onChange={(value) => updateField('default_category', value)}
                    allowCreate={false}
                    disabled={saving}
                  />
                </Field>
              </div>
              <div className="col-md-6">
                <Select
                  label="Default priority"
                  value={form.default_priority}
                  onChange={(event) => updateField('default_priority', event.target.value)}
                  disabled={saving}
                >
                  <option value="">No default priority</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </Select>
              </div>
              <div className="col-md-6">
                <Select
                  label="Assignment strategy"
                  value={form.assignment_strategy}
                  onChange={(event) => updateField('assignment_strategy', event.target.value)}
                  disabled={saving}
                >
                  {STRATEGY_OPTIONS.map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </Select>
              </div>
              <div className="col-md-6">
                <Input
                  label="Queue email address"
                  type="email"
                  value={form.email_address}
                  onChange={(event) => updateField('email_address', event.target.value)}
                  disabled={saving}
                />
              </div>
              <div className="col-md-6">
                <Field label="Queue manager">
                  <UserSelect
                    value={form.manager}
                    onChange={(value) => updateField('manager', value)}
                    disabled={saving}
                    label="Queue manager"
                  />
                </Field>
              </div>
              <div className="col-12">
                <label className="form-check">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    checked={form.allow_self_claim}
                    onChange={(event) => updateField('allow_self_claim', event.target.checked)}
                    disabled={saving}
                  />
                  <span className="form-check-label">Allow eligible queue members to claim tickets</span>
                </label>
              </div>
            </div>

            <div className="row-gap mt-3">
              <Button type="submit" disabled={saving}>
                {saving ? 'Saving...' : editing ? 'Save changes' : 'Create queue'}
              </Button>
              <Button kind="secondary" onClick={closeForm} disabled={saving}>
                Cancel
              </Button>
            </div>
          </form>
        </Modal>
      ) : null}

      {deactivateTarget ? (
        <ConfirmDialog
          title="Deactivate ticket queue?"
          message={`"${deactivateTarget.name}" will no longer be available as an active queue. Existing ticket records will be retained.`}
          confirmLabel="Deactivate queue"
          danger
          busy={deactivating}
          onConfirm={confirmDeactivate}
          onCancel={() => {
            if (!deactivating) setDeactivateTarget(null);
          }}
        />
      ) : null}

      {autoAssignTarget ? (
        <ConfirmDialog
          title="Auto-assign queue tickets?"
          message={`All currently unassigned open tickets in "${autoAssignTarget.name}" will be assigned to eligible queue members using the "${autoAssignTarget.assignment_strategy}" strategy. Ticket statuses may also change to In Progress.`}
          confirmLabel="Auto-assign tickets"
          danger
          busy={autoAssigning}
          onConfirm={confirmAutoAssign}
          onCancel={() => {
            if (!autoAssigning) setAutoAssignTarget(null);
          }}
        />
      ) : null}

      {membershipRemoveTarget ? (
        <ConfirmDialog
          title="Remove queue member?"
          message={`${membershipRemoveTarget.user_email || `User #${membershipRemoveTarget.user}`} will lose membership in "${selectedQueue?.name || 'this queue'}". The membership record will be retained as inactive history.`}
          confirmLabel="Remove member"
          danger
          busy={membershipRemoving}
          onConfirm={confirmRemoveQueueMember}
          onCancel={() => {
            if (!membershipRemoving) setMembershipRemoveTarget(null);
          }}
        />
      ) : null}
    </div>
  );
}