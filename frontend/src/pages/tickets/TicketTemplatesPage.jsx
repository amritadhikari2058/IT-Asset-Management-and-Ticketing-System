import { useCallback, useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Alert,
  Button,
  CategorySelect,
  ConfirmDialog,
  DataTable,
  EmptyState,
  Input,
  PageHeader,
  Select,
  UserSelect,
} from '../../components';
import { parseApiError } from '../../api-utils';

const EMPTY_FORM = {
  name: '',
  code: '',
  title_template: '',
  description_template: '',
  category: '',
  queue: '',
  priority: 'medium',
  default_assignee: '',
  default_status: 'open',
  required_asset: false,
  is_shared: false,
  note_templates: '[]',
  custom_fields: '{}',
};

const STATUS_OPTIONS = [
  'open',
  'in_progress',
  'waiting_requester',
  'waiting_third_party',
  'resolved',
  'closed',
  'reopened',
  'cancelled',
];

function toForm(template) {
  return {
    name: template.name ?? '',
    code: template.code ?? '',
    title_template: template.title_template ?? '',
    description_template: template.description_template ?? '',
    category: template.category ?? '',
    queue: template.queue ?? '',
    priority: template.priority || 'medium',
    default_assignee: template.default_assignee ?? '',
    default_status: template.default_status || 'open',
    required_asset: Boolean(template.required_asset),
    is_shared: Boolean(template.is_shared),
    note_templates: JSON.stringify(template.note_templates ?? [], null, 2),
    custom_fields: JSON.stringify(template.custom_fields ?? {}, null, 2),
  };
}

function parseJsonField(value, expectedType, label) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must contain valid JSON.`);
  }

  const valid = expectedType === 'array'
    ? Array.isArray(parsed)
    : parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed);

  if (!valid) {
    throw new Error(`${label} must be a JSON ${expectedType}.`);
  }
  return parsed;
}

export function TicketTemplatesPage() {
  const { isStaff, isManagerOrAdmin, user } = useAuth();

  const [templates, setTemplates] = useState([]);
  const [queues, setQueues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [editing, setEditing] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [search, setSearch] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get('/tickets/templates/');
      const data = response.data;
      setTemplates(data.results ?? data ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load ticket templates.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isStaff) return undefined;

    let active = true;
    api.get('/tickets/queues/')
      .then((response) => {
        if (active) setQueues(response.data.results ?? response.data ?? []);
      })
      .catch(() => {
        if (active) setQueues([]);
      });

    return () => {
      active = false;
    };
  }, [isStaff]);

  useEffect(() => {
    if (isStaff) loadTemplates();
  }, [isStaff, loadTemplates]);

  const isTemplateOwner = (template) => (
    Number(template.owner) === Number(user?.id)
  );

  const canEditTemplate = (template) => (
    isManagerOrAdmin || (isTemplateOwner(template) && !template.is_shared)
  );

  const canDeleteTemplate = (template) => (
    isManagerOrAdmin || isTemplateOwner(template)
  );

  const updateField = (name, value) => {
    setForm((current) => ({ ...current, [name]: value }));
  };

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
    setForm({ ...EMPTY_FORM, is_shared: false });
    setFormError('');
  };

  const openEdit = (template) => {
    if (!canEditTemplate(template)) return;
    setEditing(template);
    setFormOpen(true);
    setForm(toForm(template));
    setFormError('');
  };

  const closeForm = () => {
    if (saving) return;
    setEditing(null);
    setFormOpen(false);
    setFormError('');
  };

  const submitForm = async (event) => {
    event.preventDefault();
    if (saving) return;

    setFormError('');

    if (!form.name.trim()) {
      setFormError('Template name is required.');
      return;
    }
    if (!form.title_template.trim()) {
      setFormError('Ticket title template is required.');
      return;
    }

    let noteTemplates;
    let customFields;
    try {
      noteTemplates = parseJsonField(form.note_templates, 'array', 'Note templates');
      customFields = parseJsonField(form.custom_fields, 'object', 'Custom fields');
    } catch (e) {
      setFormError(e.message);
      return;
    }

    const payload = {
      name: form.name.trim(),
      ...(editing && form.code.trim() === String(editing.code ?? '').trim()
        ? {}
        : { code: form.code.trim() }),
      title_template: form.title_template.trim(),
      description_template: form.description_template,
      category: form.category || null,
      queue: form.queue || null,
      priority: form.priority,
      default_assignee: form.default_assignee || null,
      default_status: form.default_status,
      required_asset: Boolean(form.required_asset),
      note_templates: noteTemplates,
      custom_fields: customFields,
      is_shared: isManagerOrAdmin ? Boolean(form.is_shared) : false,
    };

    setSaving(true);
    try {
      if (editing) {
        await api.put(`/tickets/templates/${editing.id}/`, payload);
      } else {
        await api.post('/tickets/templates/', payload);
      }
      setEditing(null);
      setFormOpen(false);
      await loadTemplates();
    } catch (e) {
      setFormError(parseApiError(e).global || 'Could not save the ticket template.');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting || !canDeleteTemplate(deleteTarget)) return;

    setDeleting(true);
    setError('');
    try {
      await api.delete(`/tickets/templates/${deleteTarget.id}/`);
      setDeleteTarget(null);
      await loadTemplates();
    } catch (e) {
      setError(parseApiError(e).global || 'Could not delete the ticket template.');
    } finally {
      setDeleting(false);
    }
  };

  if (!isStaff) {
    return (
      <div className="p-4">
        <Alert variant="danger">Ticket templates are available to IT staff only.</Alert>
      </div>
    );
  }

  const normalizedSearch = search.trim().toLowerCase();
  const visibleTemplates = templates.filter((template) => {
    const matchesCategory = !categoryFilter
      || String(template.category ?? '') === String(categoryFilter);
    const matchesSearch = !normalizedSearch
      || [template.name, template.code, template.title_template, template.category_name]
        .some((value) => String(value ?? '').toLowerCase().includes(normalizedSearch));
    return matchesCategory && matchesSearch;
  });

  const columns = [
    {
      key: 'name',
      label: 'Template',
      render: (template) => (
        <div>
          <strong>{template.name}</strong>
          {template.code ? <div className="muted small">{template.code}</div> : null}
        </div>
      ),
    },
    {
      key: 'category',
      label: 'Category',
      render: (template) => template.category_name || '—',
    },
    {
      key: 'priority',
      label: 'Priority',
      render: (template) => template.priority || 'Default',
    },
    {
      key: 'visibility',
      label: 'Visibility',
      render: (template) => template.is_shared ? 'Shared' : 'Personal',
    },
    {
      key: 'owner',
      label: 'Owner',
      render: (template) => template.owner_email || '—',
    },
    {
      key: 'actions',
      label: 'Actions',
      render: (template) => canEditTemplate(template) || canDeleteTemplate(template) ? (
        <div className="row-gap">
          {canEditTemplate(template) ? (
            <Button kind="secondary" size="small" onClick={() => openEdit(template)}>
              Edit
            </Button>
          ) : null}
          {canDeleteTemplate(template) ? (
            <Button kind="secondary" size="small" onClick={() => setDeleteTarget(template)}>
              Delete
            </Button>
          ) : null}
        </div>
      ) : <span className="muted">View only</span>,
    },
  ];

  return (
    <div className="p-4">
      <PageHeader
        title="Ticket Templates"
        sub="Create and maintain reusable ticket configurations."
        actions={
          <Button onClick={openCreate}>Create template</Button>
        }
      />

      {error ? <Alert variant="danger">{error}</Alert> : null}

      {formOpen ? (
        <section className="card p-3 mb-4" aria-label={editing ? 'Edit template' : 'Create template'}>
          <h2 className="h5 mb-3">{editing ? 'Edit ticket template' : 'Create ticket template'}</h2>
          {formError ? <Alert variant="danger">{formError}</Alert> : null}

          <form onSubmit={submitForm}>
            <div className="row g-3">
              <div className="col-md-6">
                <Input
                  label="Template name"
                  value={form.name}
                  onChange={(e) => updateField('name', e.target.value)}
                  required
                  disabled={saving}
                />
              </div>
              <div className="col-md-6">
                <Input
                  label="Code (optional)"
                  value={form.code}
                  onChange={(e) => updateField('code', e.target.value)}
                  disabled={saving}
                />
              </div>
              <div className="col-12">
                <Input
                  label="Ticket title template"
                  value={form.title_template}
                  onChange={(e) => updateField('title_template', e.target.value)}
                  required
                  disabled={saving}
                />
              </div>
              <div className="col-12">
                <Input
                  label="Description template"
                  rows={3}
                  value={form.description_template}
                  onChange={(e) => updateField('description_template', e.target.value)}
                  disabled={saving}
                />
              </div>
              <div className="col-md-6">
                <label className="form-label">Ticket category</label>
                <CategorySelect
                  kind="ticket"
                  value={form.category}
                  onChange={(value) => updateField('category', value)}
                  disabled={saving}
                />
              </div>
              <div className="col-md-6">
                <Select
                  label="Queue"
                  value={form.queue}
                  onChange={(e) => updateField('queue', e.target.value)}
                  disabled={saving}
                >
                  <option value="">No default queue</option>
                  {queues.map((queue) => (
                    <option key={queue.id} value={queue.id}>{queue.name}</option>
                  ))}
                </Select>
              </div>
              <div className="col-md-6">
                <Select
                  label="Default priority"
                  value={form.priority}
                  onChange={(e) => updateField('priority', e.target.value)}
                  disabled={saving}
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </Select>
              </div>
              <div className="col-md-6">
                <Select
                  label="Default status"
                  value={form.default_status}
                  onChange={(e) => updateField('default_status', e.target.value)}
                  disabled={saving}
                >
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>
                  ))}
                </Select>
              </div>
              <div className="col-md-6">
                <label className="form-label">Default assignee</label>
                <UserSelect
                  value={form.default_assignee}
                  onChange={(value) => updateField('default_assignee', value)}
                  disabled={saving}
                  label="Default assignee"
                />
              </div>
              <div className="col-12">
                <label className="form-check">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    checked={form.required_asset}
                    onChange={(e) => updateField('required_asset', e.target.checked)}
                    disabled={saving}
                  />
                  <span className="form-check-label">Require an asset when using this template</span>
                </label>
              </div>
              <div className="col-12">
                <Input
                  label="Note templates (JSON array)"
                  rows={4}
                  value={form.note_templates}
                  onChange={(e) => updateField('note_templates', e.target.value)}
                  disabled={saving}
                />
                <p className="muted small">Expected format: an array of note objects with title, body, and is_internal fields.</p>
              </div>
              <div className="col-12">
                <Input
                  label="Custom fields (JSON object)"
                  rows={4}
                  value={form.custom_fields}
                  onChange={(e) => updateField('custom_fields', e.target.value)}
                  disabled={saving}
                />
              </div>
              {isManagerOrAdmin ? (
                <div className="col-12">
                  <label className="form-check">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      checked={form.is_shared}
                      onChange={(e) => updateField('is_shared', e.target.checked)}
                      disabled={saving}
                    />
                    <span className="form-check-label">Share this template with IT staff</span>
                  </label>
                </div>
              ) : null}
            </div>

            <div className="row-gap mt-3">
              <Button type="submit" disabled={saving}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Create template'}
              </Button>
              <Button kind="secondary" onClick={closeForm} disabled={saving}>
                Cancel
              </Button>
            </div>
          </form>
        </section>
      ) : null}

      <div className="row g-3 mb-3">
        <div className="col-md-5">
          <label className="form-label">Filter by category</label>
          <CategorySelect
            kind="ticket"
            value={categoryFilter}
            onChange={setCategoryFilter}
          />
        </div>
        <div className="col-md-7">
          <Input
            label="Search templates"
            placeholder="Search by name, code, title, or category…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {loading ? (
        <p className="page-loading">Loading templates…</p>
      ) : visibleTemplates.length === 0 ? (
        <EmptyState
          title="No templates found"
          hint={templates.length ? 'Try changing the category or search text.' : 'Create a template to reuse common ticket configurations.'}
        />
      ) : (
        <DataTable
          rows={visibleTemplates}
          keyOf={(template) => template.id}
          columns={columns}
          emptyTitle="No templates found"
        />
      )}

      {deleteTarget ? (
        <ConfirmDialog
          title="Delete ticket template?"
          message={`"${deleteTarget.name}" will be removed from the active template list.`}
          confirmLabel="Delete template"
          danger
          busy={deleting}
          onConfirm={confirmDelete}
          onCancel={() => {
            if (!deleting) setDeleteTarget(null);
          }}
        />
      ) : null}
    </div>
  );
}