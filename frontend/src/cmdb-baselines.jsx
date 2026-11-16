import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, PageHeader, LoadingRows,
  Field, Select, Input,
} from './components';
import {
  formatDate,
  CMDB_API_CONTRACT,
  CMDB_ROLES,
  CMDB_PERMISSIONS,
  BASELINE_SCOPE_LABELS,
  BASELINE_STATUS_LABELS,
} from './cmdb-utils';

export function BaselinesPage() {
  const { role } = useAuth();
  const [baselines, setBaselines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    name: '',
    code: '',
    description: '',
    scope_type: 'single_ci',
    ci: null,
    ci_group: null,
    service: null,
    environment: 'production',
    department: null,
    baseline_date: null,
    effective_from: null,
    effective_to: null,
  });

  useEffect(() => {
    let cancelled = false;
    api
      .get(CMDB_API_CONTRACT.baselinesList.endpoint)
      .then((r) => { if (!cancelled) setBaselines(r.data || []); })
      .catch(() => { if (!cancelled) setError('Failed to load baselines.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const saveBaseline = async () => {
    if (!form.name || !form.code) return;
    try {
      const r = await api.post(CMDB_API_CONTRACT.baselinesList.endpoint, form);
      setBaselines((prev) => [...prev, r.data]);
      setForm({
        name: '', code: '', description: '', scope_type: 'single_ci',
        ci: null, ci_group: null, service: null, environment: 'production',
        department: null, baseline_date: null, effective_from: null, effective_to: null,
      });
    } catch (e) {
      setError(e?.response?.data?.message || 'Failed to save baseline.');
    }
  };

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB baselines access for creation or approval.
      </div>
    );
  }

  if (loading && !baselines.length) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading baselines...</p>
      </div>
    );
  }

  if (error && !baselines.length) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Configuration Baselines"
        sub="Baseline versioning and approval"
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>New Baseline</h4>
        <Form rowGutters={16}>
          <Field label="Name *">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Production Baseline Q4 2026"
            />
          </Field>
          <Field label="Code *">
            <Input
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              placeholder="e.g. BL-2026"
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
          <Field label="Scope Type *">
            <Select
              value={form.scope_type}
              onChange={(e) => setForm({ ...form, scope_type: e.target.value })}
              aria-label="Scope Type"
            >
              <option value="single_ci">Single CI</option>
              <option value="ci_group">CI Group</option>
              <option value="service">Service</option>
              <option value="environment">Environment</option>
              <option value="department">Department</option>
            </Select>
          </Field>
          <Field label="Environment">
            <Select
              value={form.environment}
              onChange={(e) => setForm({ ...form, environment: e.target.value })}
              aria-label="Environment"
            >
              <option value="production">Production</option>
              <option value="staging">Staging</option>
              <option value="development">Development</option>
              <option value="test">Test</option>
            </Select>
          </Field>
          <div className="row-end" style={{ marginTop: 20 }}>
            <button
              type="button"
              className="btn-primary"
              onClick={saveBaseline}
              disabled={!form.name || !form.code}
            >
              Create Baseline
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setForm({
                name: '', code: '', description: '', scope_type: 'single_ci',
                ci: null, ci_group: null, service: null, environment: 'production',
                department: null, baseline_date: null, effective_from: null, effective_to: null,
              })}
            >
              Cancel
            </button>
          </div>
        </Form>
      </div>

      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'code', label: 'Code' },
            { key: 'scope_type', label: 'Scope', render: (v) => BASELINE_SCOPE_LABELS[v] || v },
            { key: 'status', label: 'Status', render: (v) => BASELINE_STATUS_LABELS[v] || v },
            { key: 'version', label: 'Version' },
            { key: 'created_by', label: 'Created By', render: (v) => (typeof v === 'object' && v !== null ? (v.username || v.name || String(v.id ?? '—')) : v || '—') },
            { key: 'approved_by', label: 'Approved By', render: (v) => (typeof v === 'object' && v !== null ? (v.username || v.name || String(v.id ?? '—')) : v || '—') },
          ]} тез
          rows={baselines}
          keyOf={(r) => r.id}
          emptyTitle="No baselines found."
          emptyHint="Add a new baseline to get started."
        />
      </div>
    </div>
  );
}

const Form = ({ rowGutters, children }) => (
  <form style={{ display: 'grid', gap: rowGutters + 'px' }} noValidate>
    {children}
  </form>
);
