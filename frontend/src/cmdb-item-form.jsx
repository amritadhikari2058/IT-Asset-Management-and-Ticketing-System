import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  ErrorSummary, Field, Input, PageHeader, Select,
} from './components';
import { parseApiError } from './api-utils';
import {
  CI_STATUS_LABELS, CI_LIFECYCLE_LABELS, CRITICALITY_LABELS,
  ENVIRONMENT_LABELS, SOURCE_LABELS, CMDB_API_CONTRACT, CMDB_PERMISSIONS,
  safeResults,
} from './cmdb-utils';

const EMPTY_FORM = {
  name: '',
  ci_type: '',
  description: '',
  status: 'planned',
  lifecycle_state: 'proposed',
  criticality: 'medium',
  environment: 'production',
  location: '',
  vendor: '',
  manufacturer: '',
  model: '',
  serial_number: '',
  hostname: '',
  ip_address: '',
  dns_name: '',
  external_reference: '',
  source: 'manual',
};

export function CiForm({ id, onSaved }) {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [form, setForm] = useState(EMPTY_FORM);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(!!id);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const isEdit = !!id;
  const canSave = CMDB_PERMISSIONS.canCreateCI(role) || CMDB_PERMISSIONS.canEditCI(role);

  // Load CI types
  useEffect(() => {
    let cancelled = false;
    api.get(CMDB_API_CONTRACT.typesList.endpoint)
      .then((r) => { if (!cancelled) setTypes(safeResults(r.data?.results ?? r.data)); })
      .catch(() => { if (!cancelled) setTypes([]); });
    return () => { cancelled = true; };
  }, []);

  // Load existing CI for edit
  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;
    setLoading(true);
    api.get(CMDB_API_CONTRACT.ciDetail.endpoint(Number(id)))
      .then((r) => {
        if (cancelled) return;
        const ci = r.data || {};
        setForm({
          ...EMPTY_FORM,
          ...Object.fromEntries(
            Object.keys(EMPTY_FORM).map((k) => [k, ci[k] ?? EMPTY_FORM[k]]),
          ),
        });
      })
      .catch((e) => {
        if (!cancelled) setError(parseApiError(e).global || 'Could not load CI.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const save = async (e) => {
    e.preventDefault();
    if (!canSave || !form.name || !form.ci_type) return;
    setSaving(true);
    setError('');
    try {
      if (isEdit) {
        await api.patch(CMDB_API_CONTRACT.ciEdit.endpoint(Number(id)), form);
      } else {
        await api.post(CMDB_API_CONTRACT.ciCreate.endpoint, form);
      }
      if (onSaved) onSaved();
    } catch (err) {
      setError(parseApiError(err).global || 'Could not save CI.');
    } finally {
      setSaving(false);
    }
  };

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB CI edit access.
      </div>
    );
  }

  if (loading) {
    return <div className="panel panel-pad"><p>Loading CI...</p></div>;
  }

  return (
    <div>
      <PageHeader
        title={isEdit ? 'Edit CI' : 'New CI'}
        sub={isEdit ? `CI ID: ${id}` : 'Fill in the CI details below'}
      />

      {error && <ErrorSummary parsed={{ global: error }} />}

      <form className="panel panel-pad" onSubmit={save} noValidate>
        <Field label="CI Name *">
          <Input value={form.name} onChange={(e) => setField('name', e.target.value)} />
        </Field>

        <Field label="CI Type *">
          <Select
            value={form.ci_type}
            onChange={(e) => setField('ci_type', e.target.value)}
            aria-label="CI Type"
          >
            <option value="">Select a type</option>
            {types.map((t) => (
              <option key={t.id} value={t.id}>{t.name || t.code || t.id}</option>
            ))}
          </Select>
        </Field>

        <Field label="Description">
          <Input
            value={form.description}
            type="textarea"
            onChange={(e) => setField('description', e.target.value)}
          />
        </Field>

        <Field label="Status">
          <Select value={form.status} onChange={(e) => setField('status', e.target.value)} aria-label="Status">
            {Object.entries(CI_STATUS_LABELS).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </Select>
        </Field>

        <Field label="Lifecycle State">
          <Select
            value={form.lifecycle_state}
            onChange={(e) => setField('lifecycle_state', e.target.value)}
            aria-label="Lifecycle State"
          >
            {Object.entries(CI_LIFECYCLE_LABELS).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </Select>
        </Field>

        <Field label="Criticality">
          <Select
            value={form.criticality}
            onChange={(e) => setField('criticality', e.target.value)}
            aria-label="Criticality"
          >
            {Object.entries(CRITICALITY_LABELS).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </Select>
        </Field>

        <Field label="Environment">
          <Select
            value={form.environment}
            onChange={(e) => setField('environment', e.target.value)}
            aria-label="Environment"
          >
            {Object.entries(ENVIRONMENT_LABELS).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </Select>
        </Field>

        <Field label="Location">
          <Input value={form.location} onChange={(e) => setField('location', e.target.value)} />
        </Field>

        <Field label="Vendor">
          <Input value={form.vendor} onChange={(e) => setField('vendor', e.target.value)} />
        </Field>

        <Field label="Manufacturer">
          <Input value={form.manufacturer} onChange={(e) => setField('manufacturer', e.target.value)} />
        </Field>

        <Field label="Model">
          <Input value={form.model} onChange={(e) => setField('model', e.target.value)} />
        </Field>

        <Field label="Serial Number">
          <Input value={form.serial_number} onChange={(e) => setField('serial_number', e.target.value)} />
        </Field>

        <Field label="Hostname">
          <Input value={form.hostname} onChange={(e) => setField('hostname', e.target.value)} />
        </Field>

        <Field label="IP Address">
          <Input value={form.ip_address} onChange={(e) => setField('ip_address', e.target.value)} />
        </Field>

        <Field label="DNS Name">
          <Input value={form.dns_name} onChange={(e) => setField('dns_name', e.target.value)} />
        </Field>

        <Field label="External Reference">
          <Input
            value={form.external_reference}
            onChange={(e) => setField('external_reference', e.target.value)}
          />
        </Field>

        <Field label="Source">
          <Select value={form.source} onChange={(e) => setField('source', e.target.value)} aria-label="Source">
            {Object.entries(SOURCE_LABELS).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </Select>
        </Field>

        <div className="row-end" style={{ marginTop: 20 }}>
          {!canSave && <span className="field-hint">You do not have permission to save CIs.</span>}
          <button type="submit" className="btn-primary" disabled={!canSave || saving || !form.name || !form.ci_type}>
            {saving ? 'Saving…' : (isEdit ? 'Update CI' : 'Create CI')}
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => { window.location.hash = '#/cmdb/items'; }}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
