import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  DataTable, PageHeader, LoadingRows,
  Field, Select, Input,
} from './components';
import { parseApiError } from './api-utils';
import {
  safeResults,
  CMDB_API_CONTRACT,
  CMDB_PERMISSIONS,
  BASELINE_SCOPE_LABELS,
  BASELINE_STATUS_LABELS,
} from './cmdb-utils';

const EMPTY_FORM = {
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
};

function personLabel(value) {
  if (value == null) return '—';
  if (typeof value === 'object') return value.username || value.name || value.email || String(value.id ?? '—');
  return String(value);
}

export function BaselinesPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [baselines, setBaselines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [compareResult, setCompareResult] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);

  const canManage = CMDB_PERMISSIONS.canCreateBaselines(role);

  useEffect(() => {
    let cancelled = false;
    api
      .get(CMDB_API_CONTRACT.baselinesList.endpoint)
      .then((r) => {
        if (!cancelled) setBaselines(safeResults(r.data?.results ?? r.data));
      })
      .catch(() => { if (!cancelled) setError('Failed to load baselines.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const replaceBaseline = (updated) => {
    if (!updated || updated.id == null) return;
    setBaselines((prev) => prev.map((b) => (b.id === updated.id ? { ...b, ...updated } : b)));
  };

  const saveBaseline = async () => {
    if (!form.name || !form.code) return;
    setError('');
    try {
      const r = await api.post(CMDB_API_CONTRACT.baselinesList.endpoint, form);
      const saved = r.data && r.data.id != null ? r.data : { ...form, id: Date.now(), status: 'draft' };
      setBaselines((prev) => [...prev, saved]);
      setForm(EMPTY_FORM);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to save baseline.');
    }
  };

  const baselineAction = async (baseline, action) => {
    if (!baseline) return;
    setError('');
    try {
      const url = `${CMDB_API_CONTRACT.baselinesList.endpoint}/${baseline.id}/${action}`;
      const r = action === 'approve' || action === 'supersede'
        ? await api.patch(url)
        : await api.post(url);
      replaceBaseline(r.data);
    } catch (e) {
      if (e?.response?.status === 403 && action === 'approve') {
        setError('Creator cannot approve own baseline.');
        return;
      }
      setError(parseApiError(e).global || `Could not ${action} baseline.`);
    }
  };

  const compareBaselines = async (baseline) => {
    if (!baseline) return;
    setError('');
    try {
      const r = await api.get(`${CMDB_API_CONTRACT.baselinesList.endpoint}/${baseline.id}/compare`);
      setCompareResult(r.data || {});
    } catch (e) {
      setError(parseApiError(e).global || 'Could not compare baselines.');
    }
  };

  // Employees have no CMDB baseline access
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB baseline access.
      </div>
    );
  }

  const active = baselines[0];

  return (
    <div>
      <PageHeader
        title="Configuration Baselines"
        sub="Baseline versioning and approval"
      />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {loading && (
        <div className="panel panel-pad">
          <LoadingRows n={4} />
          <p>Loading baselines...</p>
        </div>
      )}

      {!canManage && (
        <div className="panel panel-pad">
          <p className="muted">
            Baseline creation and approval requires System Admin permission.
            You can still view baselines and drift findings.
          </p>
        </div>
      )}

      {canManage && (
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
              <button type="button" className="btn-ghost" onClick={() => setForm(EMPTY_FORM)}>
                Cancel
              </button>
            </div>
          </Form>
        </div>
      )}

      {/* Lifecycle actions act on the selected (first) baseline */}
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>Baseline Actions</h4>
        <div className="row-gap">
          <button type="button" className="btn-small" disabled={!active} onClick={() => baselineAction(active, 'submit')}>
            Submit
          </button>
          <button type="button" className="btn-small" disabled={!active} onClick={() => baselineAction(active, 'approve')}>
            Approve
          </button>
          <button type="button" className="btn-small" disabled={!active} onClick={() => baselineAction(active, 'supersede')}>
            Supersede
          </button>
          <button type="button" className="btn-small" disabled={!active} onClick={() => compareBaselines(active)}>
            Compare
          </button>
        </div>
        {compareResult && (
          <p className="muted small">
            Comparison loaded for baseline #{active?.id}.
          </p>
        )}
      </div>

      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'name', label: 'Name', render: (row) => row.name || '—' },
            { key: 'code', label: 'Code', render: (row) => row.code || '—' },
            { key: 'scope', label: 'Scope', render: (row) => BASELINE_SCOPE_LABELS[row.scope] || row.scope || row.scope_type || '—' },
            { key: 'status', label: 'Status', render: (row) => BASELINE_STATUS_LABELS[row.status] || row.status || '—' },
            { key: 'version', label: 'Version', render: (row) => row.version ?? '—' },
            { key: 'created_by', label: 'Created By', render: (row) => personLabel(row.created_by) },
            { key: 'approved_by', label: 'Approved By', render: (row) => personLabel(row.approved_by) },
          ]}
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
