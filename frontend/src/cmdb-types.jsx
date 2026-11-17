import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, ConfirmDialog, Modal,
} from './components';
import {
  formatDate, formatPercent, ciStatusBadgeVariant,
  criticalityBadgeVariant, safeResults, formatVerificationAge,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
  CI_TYPE_CATEGORY_LABELS, CI_STATUS_LABELS, CI_LIFECYCLE_LABELS,
  CRITICALITY_LABELS, ENVIRONMENT_LABELS, SOURCE_LABELS,
  MONITORING_STATE_LABELS, DATA_CLASSIFICATION_LABELS,
  VALIDATED_SYSTEM_IMPACT_LABELS, RELATIONSHIP_TYPE_LABELS,
  RELATIONSHIP_STATUS_LABELS, RELATIONSHIP_CONFIDENCE_LABELS,
  BASELINE_SCOPE_LABELS, BASELINE_STATUS_LABELS,
  DRIFT_TYPE_LABELS, DRIFT_SEVERITY_LABELS, DRIFT_STATUS_LABELS,
} from './cmdb-utils';
import { parseApiError } from './api-utils';

export function CiTypesPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    name: '', code: '', description: '', category: 'other',
    icon: '', color: '', is_active: true, schema: [],
    required_attributes: [],
  });
  const [deleteModal, setDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [warnUsed, setWarnUsed] = useState(false);

  // Load CI types
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(CMDB_API_CONTRACT.typesList.endpoint)
      .then((r) => { if (!cancelled) setTypes(r.data); })
      .catch((e) => { setError('Could not load CI types.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Create / update CI type
  const saveType = async () => {
    setError('');
    try {
      if (form.id) {
        await api.patch(`/cmdb/types/${form.id}`, form);
      } else {
        await api.post(CMDB_API_CONTRACT.typeCreate.endpoint, form);
      }
      setError('');
      const saved = await api.get(CMDB_API_CONTRACT.typesList.endpoint);
      setTypes(safeResults(saved.data?.results ?? saved.data));
      setForm({ name: '', code: '', description: '', category: 'other',
        icon: '', color: '', is_active: true, schema: [], required_attributes: [] });
    } catch (e) {
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not save CI type.');
    }
  };

  // Delete CI type
  const handleDelete = async (typeId) => {
    setDeleting(true);
    setWarnUsed(false);
    try {
      // Check if type is used by existing CIs
      const typeUsed = types.some((t) => t.id === typeId && t.ci_count > 0);
      if (typeUsed) {
        setWarnUsed(true);
        setDeleting(false);
        return;
      }
      await api.delete(`/cmdb/types/${typeId}`);
      setTypes(prev => prev.filter((t) => t.id !== typeId));
    } catch (e) {
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not delete CI type.');
    } finally {
      setDeleting(false);
      setDeleteModal(false);
    }
  };

  // Employee denied
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB CI Types access.
      </div>
    );
  }

  if (loading && !types.length) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading CI types...</p>
      </div>
    );
  }

  if (error && !types.length) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader
        title="CI Types"
        sub="Configuration Item Type management"
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Form */}
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>{form.id ? 'Edit CI Type' : 'New CI Type'}</h4>
        <Form rowGutters={16}>
          <Field label="Name *">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Server"
              disabled={false}
            />
          </Field>

          <Field label="Code *">
            <Input
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              placeholder="e.g. SERVER"
              disabled={false}
            />
          </Field>

          <Field label="Description">
            <Input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              type="textarea"
              placeholder="Optional description"
            />
          </Field>

          <Field label="Category">
            <Select
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              aria-label="Category"
            >
              <option value="hardware">Hardware</option>
              <option value="software">Software</option>
              <option value="network">Network</option>
              <option value="other">Other</option>
            </Select>
          </Field>

          <Field label="Icon">
            <Input
              value={form.icon}
              onChange={(e) => setForm({ ...form, icon: e.target.value })}
              placeholder="e.g. server"
              disabled={false}
            />
          </Field>

          <Field label="Color">
            <Input
              value={form.color}
              onChange={(e) => setForm({ ...form, color: e.target.value })}
              placeholder="#4A90E2"
              disabled={false}
            />
          </Field>

          <Field label="Active">
            <Select
              value={form.is_active ? 'true' : 'false'}
              onChange={(e) => setForm({ ...form, is_active: e.target.value === 'true' })}
              aria-label="Active"
            >
              <option value="true">Yes</option>
              <option value="false">No</option>
            </Select>
          </Field>

          <Field label="Schema (required attributes)">
            <Input
              value={form.required_attributes?.length || 0 ? JSON.stringify(form.required_attributes).slice(0, 200) : ''}
              type="textarea"
              placeholder='Required attributes as JSON array, e.g. [{"key":"serial_number","label":"Serial Number","type":"text","required":true}]'
              disabled={false}
            />
            <p className="muted small">Schema defines dynamic attributes for CIs of this type.</p>
          </Field>

          <div className="row-end" style={{ marginTop: 20 }}>
            <button
              type="button"
              className="btn-primary"
              onClick={saveType}
              disabled={!form.name || !form.code}
            >
              {form.id ? 'Update Type' : 'Create Type'}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setForm({ name: '', code: '', description: '', category: 'other',
                icon: '', color: '', is_active: true, schema: [], required_attributes: [] })}
              disabled={false}
            >
              Cancel
            </button>
          </div>
        </Form>
      </div>

      {/* Types table */}
      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'name', label: 'Name', render: (row) => row.name || '—' },
            { key: 'code', label: 'Code', render: (row) => row.code || '—' },
            { key: 'category', label: 'Category', render: (row) => CI_TYPE_CATEGORY_LABELS[row.category] || row.category || '—' },
            { key: 'is_active', label: 'Active', render: (row) => (row.is_active ? 'Yes' : 'No') },
            { key: 'ci_count', label: 'CI Count', render: (row) => row.ci_count ?? 0 },
            { key: 'is_system', label: 'System Type', render: (row) => (row.is_system ? 'Yes' : 'No') },
          ]}
          rows={types}
          keyOf={(r) => r.id}
          emptyTitle="No CI types found."
          emptyHint="Add a new CI type to get started."
        />
      </div>

      {/* Delete warning */}
      {warnUsed && (
        <div className="error-summary" role="alert">
          This CI Type cannot be deleted because it is used by existing CIs. Consider deactivating it instead.
        </div>
      )}
    </div>
  );
}

// ── Simple form wrapper ──────────────────────────────────────────────
const Form = ({ rowGutters, children }) => (
  <form
    style={{ display: 'grid', gap: rowGutters + 'px' }}
    noValidate
  >
    {children}
  </form>
);