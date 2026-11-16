import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, ConfirmDialog, Modal,
} from './components';
import {
  formatDate, formatDateTime, safeResults,
  CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
  RELATIONSHIP_TYPE_LABELS, RELATIONSHIP_STATUS_LABELS,
  RELATIONSHIP_CONFIDENCE_LABELS,
} from './cmdb-utils';

export function CiRelationshipsPage({ match: { params: { id } } }) {
  const { role } = useAuth();
  const [relationships, setRelationships] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    direction: 'outgoing',
    target_ci: null,
    relationship_type: '',
    description: '',
    valid_from: null,
    valid_to: null,
    confidence: 'confirmed',
  });
  const [targetCis, setTargetCis] = useState([]);
  const [loadingTargets, setLoadingTargets] = useState(true);

  // Load relationships
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(`${CMDB_API_CONTRACT.relationshipsList.endpoint}?source_ci=${id}`)
      .then((r) => { if (!cancelled) setRelationships(r.data); })
      .catch((e) => { setError('Could not load relationships.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  // Load available target CIs (inaccessible ones absent from selector)
  useEffect(() => {
    let cancelled = false;
    setLoadingTargets(true);
    api.get('/cmdb/items/')
      .then((r) => { if (!cancelled) setTargetCis(r.data); })
      .catch((e) => setTargetCis([]))
      .finally(() => { if (!cancelled) setLoadingTargets(false); });
    return () => { cancelled = true; };
  }, []);

  // Save relationship
  const saveRelationship = async () => {
    setError('');
    try {
      await api.post(CMDB_API_CONTRACT.relationshipCreate.endpoint, form);
      setError('');
      // Refresh relationships
      setRelationships(prev => {
        let cancelled = false;
        api.get(`${CMDB_API_CONTRACT.relationshipsList.endpoint}?source_ci=${params.id}`)
          .then((r) => { if (!cancelled) setRelationships(r.data); })
          .catch(() => {});
        return prev;
      });
      setForm({ direction: 'outgoing', target_ci: null, relationship_type: '',
        description: '', valid_from: null, valid_to: null, confidence: 'confirmed' });
    } catch (e) {
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not create relationship.');
    }
  };

  // Employee denied
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB relationship access.
      </div>
    );
  }

  if (loading && !relationships.length) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading relationships...</p>
      </div>
    );
  }

  if (error && !relationships.length) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader
        title="CI Relationships"
        sub={`Relationships for CI #${params.id}`}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Form */}
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>{form.target_ci ? 'Edit Relationship' : 'New Relationship'}</h4>
        <Form rowGutters={16}>
          <Field label="Direction *">
            <Select
              onChange={(e) => setForm({ ...form, direction: e.target.value })}
              aria-label="Direction"
            >
              <option value="outgoing">Outgoing (this CI → other)</option>
              <option value="incoming">Incoming (other → this CI)</option>
            </Select>
          </Field>

          <Field label="Related CI *">
            <Select
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
              onChange={(e) => setForm({ ...form, relationship_type: e.target.value })}
              aria-label="Relationship Type"
            >
              <option value="">Select relationship type</option>
              {RELATIONSHIP_TYPE_LABELS ? Object.entries(RELATIONSHIP_TYPE_LABELS).map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              )) : []}
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
              value={form.valid_from ? new Date(form.valid_from).toISOString().split('T')[0] : ''}
              onChange={(e) => setForm({ ...form, valid_from: e.target.value || null })}
            />
          </Field>

          <Field label="Valid To">
            <Input
              type="date"
              value={form.valid_to ? new Date(form.valid_to).toISOString().split('T')[0] : ''}
              onChange={(e) => setForm({ ...form, valid_to: e.target.value || null })}
            />
          </Field>

          <Field label="Confidence">
            <Select
              onChange={(e) => setForm({ ...form, confidence: e.target.value })}
              aria-label="Confidence"
            >
              <option value="confirmed">Confirmed</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="unknown">Unknown</option>
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
              onClick={() => setForm({ direction: 'outgoing', target_ci: null, relationship_type: '',
                description: '', valid_from: null, valid_to: null, confidence: 'confirmed' })}
              disabled={false}
            >
              Cancel
            </button>
          </div>
        </Form>
      </div>

      {/* Relationships table */}
      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'relationship_type', label: 'Relationship', render: (v) => RELATIONSHIP_TYPE_LABELS[v] || v },
            { key: 'target_ci_number', label: 'Related CI', render: (v) => v || '—' },
            { key: 'status', label: 'Status', render: (v) => RELATIONSHIP_STATUS_LABELS[v] || v },
            { key: 'confidence', label: 'Confidence', render: (v) => RELATIONSHIP_CONFIDENCE_LABELS[v] || v },
            { key: 'source', label: 'Source', render: (v) => v || '—' },
            { key: 'valid_from', label: 'Valid From', render: (v) => v ? formatDateTime(v) : '—' },
            { key: 'valid_to', label: 'Valid To', render: (v) => v ? formatDateTime(v) : '—' },
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