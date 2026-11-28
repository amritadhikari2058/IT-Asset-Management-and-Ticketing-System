import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Badge,
  Button,
  Input,
  Select,
  Alert,
  DataTable,
  EmptyState,
  PageHeader,
} from '../../components';
import { parseApiError } from '../../api-utils';

const EMPTY_FORM = {
  title: '',
  code: '',
  body: '',
  visibility: 'internal_note',
  category: '',
  queue: '',
  queue_name: '',
  is_shared: false,
};

export function CannedResponsesPage() {
  const { isEmployee, isManagerOrAdmin } = useAuth();

  const [responses, setResponses] = useState([]);
  const [queues, setQueues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });

  const fetchResponses = async () => {
    setLoading(true);
    setError('');

    try {
      const response = await api.get('/tickets/canned-responses/');
      setResponses(response.data.results ?? response.data ?? []);
    } catch (e) {
      setError(
        parseApiError(e).global || 'Failed to load canned responses.'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResponses();
  }, []);

  useEffect(() => {
    let active = true;

    api.get('/tickets/queues/')
      .then((response) => {
        if (!active) return;
        const data = response.data;
        setQueues(data.results ?? data ?? []);
      })
      .catch(() => {
        if (active) setQueues([]);
      });

    return () => {
      active = false;
    };
  }, []);

  const updateField = (field, value) => {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setEditingId(null);
    setCreating(false);
    setError('');
  };

  const startCreate = () => {
    setForm({ ...EMPTY_FORM });
    setEditingId(null);
    setError('');
    setCreating(true);
  };

  const startEdit = (response) => {
    setForm({
      title: response.title || '',
      code: response.code || '',
      body: response.body || '',
      visibility: response.visibility || 'internal_note',
      category: response.category || '',
      queue: response.queue == null ? '' : String(response.queue),
      queue_name: response.queue_name || '',
      is_shared: !!response.is_shared,
    });

    setEditingId(response.id);
    setCreating(true);
    setError('');
  };

  const saveResponse = async () => {
    if (!form.title.trim() || !form.body.trim()) {
      setError('Title and response body are required.');
      return;
    }

    const payload = {
      title: form.title.trim(),
      code: form.code.trim(),
      body: form.body.trim(),
      visibility: form.visibility,
      category: form.category.trim(),
      queue: form.queue ? Number(form.queue) : null,
      is_shared: isManagerOrAdmin ? form.is_shared : false,
    };

    setSaving(true);
    setError('');

    try {
      if (editingId !== null) {
        await api.put(
          `/tickets/canned-responses/${editingId}/`,
          payload
        );
      } else {
        await api.post('/tickets/canned-responses/', payload);
      }

      resetForm();
      await fetchResponses();
    } catch (e) {
      setError(
        parseApiError(e).global || 'Failed to save canned response.'
      );
    } finally {
      setSaving(false);
    }
  };

  const deleteResponse = async (response) => {
    const confirmed = window.confirm(
      `Delete canned response "${response.title}"?`
    );

    if (!confirmed) return;

    setError('');

    try {
      await api.delete(
        `/tickets/canned-responses/${response.id}/`
      );

      await fetchResponses();
    } catch (e) {
      setError(
        parseApiError(e).global || 'Failed to delete canned response.'
      );
    }
  };

  if (isEmployee) {
    return (
      <div className="py-4">
        <Alert variant="danger">
          Access denied. Employees cannot manage canned responses.
        </Alert>
      </div>
    );
  }

  return (
    <div className="p-4">
      <PageHeader
        title="Canned Responses"
        subtitle="Manage shared and personal canned responses"
      />

      {error && (
        <div className="mb-3">
          <Alert variant="danger">{error}</Alert>
        </div>
      )}

      {!creating && (
        <div className="mb-4">
          <Button variant="primary" onClick={startCreate}>
            Create Canned Response
          </Button>
        </div>
      )}

      {creating && (
        <div className="mb-4">
          <PageHeader
            title={editingId !== null ? 'Edit Canned Response' : 'Create Canned Response'}
            subtitle="Enter the response details below"
          />

          <div className="row g-3">
            <Input
              label="Title"
              value={form.title}
              onChange={(e) => updateField('title', e.target.value)}
              placeholder="e.g. Password Reset Instructions"
              maxLength={200}
              required
            />

            <Input
              label="Code (optional)"
              value={form.code}
              onChange={(e) => updateField('code', e.target.value)}
              placeholder="e.g. PASSWORD-RESET"
              maxLength={60}
            />

            <Input
              label="Category"
              value={form.category}
              onChange={(e) => updateField('category', e.target.value)}
              placeholder="e.g. hardware, software, general"
              maxLength={100}
            />

            <Select
              label="Queue"
              value={form.queue}
              onChange={(e) => updateField('queue', e.target.value)}
              disabled={saving}
            >
              <option value="">No queue</option>
              {form.queue && !queues.some(
                (queue) => String(queue.id) === form.queue
              ) && (
                <option value={form.queue}>
                  {form.queue_name || `Queue #${form.queue}`} (inactive or unavailable)
                </option>
              )}
              {queues.map((queue) => (
                <option key={queue.id} value={queue.id}>
                  {queue.name}
                </option>
              ))}
            </Select>

            <Select
              label="Visibility"
              value={form.visibility}
              onChange={(e) => updateField('visibility', e.target.value)}
            >
              <option value="internal_note">Internal Note</option>
              <option value="public_reply">Public Reply</option>
              <option value="both">Both</option>
            </Select>

            <label className="field">
              <span>Response Body</span>
              <textarea
                className="input"
                rows={5}
                value={form.body}
                onChange={(e) => updateField('body', e.target.value)}
                placeholder="Enter the canned response text..."
                required
              />
            </label>

            {isManagerOrAdmin && (
              <label className="field">
                <span>
                  <input
                    type="checkbox"
                    checked={form.is_shared}
                    onChange={(e) =>
                      updateField('is_shared', e.target.checked)
                    }
                  />
                  {' '}Make this response shared with IT staff
                </span>
              </label>
            )}
          </div>

          <div className="row-gap mt-3">
            <Button
              variant="secondary"
              onClick={resetForm}
              disabled={saving}
            >
              Cancel
            </Button>

            <Button
              variant="primary"
              onClick={saveResponse}
              disabled={saving}
            >
              {saving
                ? 'Saving...'
                : editingId !== null
                  ? 'Update Response'
                  : 'Save Response'}
            </Button>
          </div>
        </div>
      )}

      {!creating && (
        <div>
          {loading ? (
            <p className="page-loading">Loading canned responses...</p>
          ) : responses.length === 0 ? (
            <EmptyState
              icon="💬"
              title="No Responses"
              text="No canned responses found. Create your first response to get started."
            />
          ) : (
            <DataTable
              rows={responses}
              keyOf={(response) => response.id}
              columns={[
                {
                  key: 'title',
                  label: 'Title',
                  render: (response) => (
                    <strong>{response.title}</strong>
                  ),
                },
                {
                  key: 'code',
                  label: 'Code',
                  render: (response) => response.code || '-',
                },
                {
                  key: 'visibility',
                  label: 'Visibility',
                  render: (response) => (
                    <Badge
                      kind="status"
                      value={response.visibility}
                    />
                  ),
                },
                {
                  key: 'category',
                  label: 'Category',
                  render: (response) => response.category || '-',
                },
                {
                  key: 'queue_name',
                  label: 'Queue',
                  render: (response) => response.queue_name || '-',
                },
                {
                  key: 'is_shared',
                  label: 'Sharing',
                  render: (response) =>
                    response.is_shared ? 'Shared' : 'Personal',
                },
                {
                  key: 'usage_count',
                  label: 'Uses',
                  render: (response) => response.usage_count ?? 0,
                },
                {
                  key: 'actions',
                  label: 'Actions',
                  render: (response) => (
                    <div className="row-gap">
                      <Button
                        variant="secondary"
                        size="small"
                        onClick={() => startEdit(response)}
                      >
                        Edit
                      </Button>

                      <Button
                        variant="danger"
                        size="small"
                        onClick={() => deleteResponse(response)}
                      >
                        Delete
                      </Button>
                    </div>
                  ),
                },
              ]}
            />
          )}
        </div>
      )}
    </div>
  );
}
