import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input,
} from './components';
import { parseApiError } from './api-utils';
import {
  formatDateTime, safeResults,
  CMDB_API_CONTRACT, CMDB_PERMISSIONS,
  RELATIONSHIP_TYPE_LABELS, RELATIONSHIP_STATUS_LABELS,
  RELATIONSHIP_CONFIDENCE_LABELS,
} from './cmdb-utils';

const EMPTY_FORM = {
  direction: 'outgoing',
  target_ci: null,
  relationship_type: '',
  description: '',
  valid_from: null,
  valid_to: null,
  confidence: 'confirmed',
};

export function CiRelationshipsPage({ match: { params: { id } } }) {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [relationships, setRelationships] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState(EMPTY_FORM);
  const [targetCis, setTargetCis] = useState([]);

  // Load relationships for this CI
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(`${CMDB_API_CONTRACT.relationshipsList.endpoint}?source_ci=${id}`)
      .then((r) => {
        if (cancelled) return;
        setRelationships(safeResults(r.data?.results ?? r.data));
      })
      .catch(() => { if (!cancelled) setError('Could not load relationships.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  // Load available target CIs (inaccessible CIs are absent from the response)
  useEffect(() => {
    let cancelled = false;
    api.get(CMDB_API_CONTRACT.ciList.endpoint)
      .then((r) => { if (!cancelled) setTargetCis(safeResults(r.data?.results ?? r.data)); })
      .catch(() => { if (!cancelled) setTargetCis([]); });
    return () => { cancelled = true; };
  }, []);

  const refreshRelationships = async () => {
    const r = await api.get(`${CMDB_API_CONTRACT.relationshipsList.endpoint}?source_ci=${id}`);
    setRelationships(safeResults(r.data?.results ?? r.data));
  };

  const saveRelationship = async () => {
    setError('');
    try {
      await api.post(CMDB_API_CONTRACT.relationshipCreate.endpoint, form);
      await refreshRelationships();
      setForm(EMPTY_FORM);
    } catch (e) {
      const status = e?.response?.status;
      if (status === 404) {
        setError('Related CI not found.');
        return;
      }
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not create relationship.');
    }
  };

  const setStatus = async (relationshipId, status) => {
    setError('');
    try {
      await api.patch(`${CMDB_API_CONTRACT.relationshipsList.endpoint}/${relationshipId}`, { status });
      await refreshRelationships();
    } catch (e) {
      setError(parseApiError(e).global || 'Could not update relationship.');
    }
  };

  const inverse = relationships.filter((rel) => rel.direction === 'incoming' || rel.inverse);
  const canManage = CMDB_PERMISSIONS.canCreateRelationship(role);

  // Employees have no CMDB relationship access
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB relationship access.
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="CI Relationships"
        sub={`Read-only view of relationships for CI #${id}`}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {loading && (
        <div className="panel panel-pad">
          <LoadingRows n={3} />
          <p>Loading relationships...</p>
        </div>
      )}

      {/* Form */}
      {canManage && (
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>{form.target_ci ? 'Edit Relationship' : 'New Relationship'}</h4>
        <Form rowGutters={16}>
          <Field label="Direction *">
            <Select
              value={form.direction}
              onChange={(e) => setForm({ ...form, direction: e.target.value })}
              aria-label="Direction"
            >
              <option value="outgoing">Outgoing (this CI → other)</option>
              <option value="incoming">Incoming (other → this CI)</option>
            </Select>
          </Field>

          <Field label="Related CI *">
            <Select
              value={form.target_ci ?? ''}
              onChange={(e) => setForm({ ...form, target_ci: e.target.value ? Number(e.target.value) : null })}
              aria-label="Related CI"
            >
              <option value="">Select a CI</option>
              {targetCis.map((ci) => (
                <option key={ci.id} value={ci.id}>
                  {ci.ci_number || ci.name} ({ci.id})
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Relationship Type *">
            <Select
              value={form.relationship_type}
              onChange={(e) => setForm({ ...form, relationship_type: e.target.value })}
              aria-label="Relationship Type"
            >
              <option value="">Select relationship type</option>
              {Object.entries(RELATIONSHIP_TYPE_LABELS).map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </Select>
          </Field>

          <Field label="Description">
            <Input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Optional description"
            />
          </Field>

          <Field label="Valid From">
            <Input
              type="date"
              value={form.valid_from || ''}
              onChange={(e) => setForm({ ...form, valid_from: e.target.value || null })}
            />
          </Field>

          <Field label="Valid To">
            <Input
              type="date"
              value={form.valid_to || ''}
              onChange={(e) => setForm({ ...form, valid_to: e.target.value || null })}
            />
          </Field>

          <Field label="Confidence">
            <Select
              value={form.confidence}
              onChange={(e) => setForm({ ...form, confidence: e.target.value })}
              aria-label="Confidence"
            >
              {Object.entries(RELATIONSHIP_CONFIDENCE_LABELS).map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </Select>
          </Field>

          <div className="row-end" style={{ marginTop: 20 }}>
            <button
              type="button"
              className="btn-primary"
              onClick={saveRelationship}
              disabled={!form.relationship_type || !form.target_ci}
            >
              {form.target_ci ? 'Update Relationship' : 'Create Relationship'}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setForm(EMPTY_FORM)}
            >
              Cancel
            </button>
          </div>
        </Form>
        <p className="muted small">
          Duplicate active relationships are rejected by the backend. Hierarchy cycles are rejected
          by the backend as well.
        </p>
      </div>
      )}

      {/* Relationship actions */}
      {canManage && (
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>Relationship Actions</h4>
        <div className="row-gap">
          <button
            type="button"
            className="btn-small"
            disabled={!relationships.length}
            onClick={() => setStatus(relationships[0]?.id, 'active')}
          >
            Activate
          </button>
          <button
            type="button"
            className="btn-small"
            disabled={!relationships.length}
            onClick={() => setStatus(relationships[0]?.id, 'inactive')}
          >
            Deactivate
          </button>
        </div>
      </div>
      )}

      {!canManage && (
        <div className="panel panel-pad">
          <p className="muted">
            Read-only view. Creating or activating relationships requires IT Manager
            or System Admin permission.
          </p>
        </div>
      )}

      {/* Inverse relationships */}
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>Inverse Relationships</h4>
        {inverse.length > 0 ? (
          <ul className="mini-list">
            {inverse.map((rel) => (
              <li key={rel.id} className="mini-item">
                {rel.relationship_type} — {rel.source_ci_number || '—'}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">
            No inverse relationships recorded. Relationships viewed from the other CI appear
            here with read-only direction semantics.
          </p>
        )}
      </div>

      {/* Relationships table */}
      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'relationship_type', label: 'Relationship', render: (row) => RELATIONSHIP_TYPE_LABELS[row.relationship_type] || row.relationship_type || '—' },
            { key: 'target_ci_number', label: 'Related CI', render: (row) => row.target_ci_number || '—' },
            { key: 'status', label: 'Status', render: (row) => RELATIONSHIP_STATUS_LABELS[row.status] || row.status || '—' },
            { key: 'confidence', label: 'Confidence', render: (row) => RELATIONSHIP_CONFIDENCE_LABELS[row.confidence] || row.confidence || '—' },
            { key: 'valid_from', label: 'Valid From', render: (row) => row.valid_from ? formatDateTime(row.valid_from) : '—' },
            { key: 'valid_to', label: 'Valid To', render: (row) => row.valid_to ? formatDateTime(row.valid_to) : '—' },
          ]}
          rows={relationships}
          keyOf={(r) => r.id}
          emptyTitle="No relationships found."
          emptyHint="Add a new relationship to link CIs."
        />
      </div>
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
