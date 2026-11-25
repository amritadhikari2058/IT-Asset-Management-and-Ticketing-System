import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import { ErrorSummary, Field, Input, LoadingRows, PageHeader, Select } from '../../components';
import { parseApiError } from '../../api-utils';
import {
  CI_LIFECYCLE_LABELS,
  CI_STATUS_LABELS,
  CRITICALITY_LABELS,
  DATA_CLASSIFICATION_LABELS,
  ENVIRONMENT_LABELS,
  MONITORING_STATE_LABELS,
  SOURCE_LABELS,
  VALIDATED_SYSTEM_IMPACT_LABELS,
  CMDB_API_CONTRACT,
  CMDB_PERMISSIONS,
  safeResults,
} from '../../shared/cmdb-utils';

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
  version: '',
  hostname: '',
  ip_address: '',
  dns_name: '',
  external_reference: '',
  source: 'manual',
  monitoring_state: 'unknown',
  data_classification: 'internal',
  validated_system_impact: 'none',
};

function toPayload(form) {
  const payload = {};
  Object.entries(form).forEach(([k, v]) => {
    if (v === '' || v == null) return;
    payload[k] = v;
  });
  // keep empty-able text fields explicit only when editing is not necessary; avoid sending empty ip_address
  if (payload.ip_address === '') delete payload.ip_address;
  if (payload.ci_type) payload.ci_type = Number(payload.ci_type);
  return payload;
}

export function CiForm({ id: idProp, match, onSaved }) {
  const id = idProp ?? match?.params?.id;
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [form, setForm] = useState(EMPTY_FORM);
  const [recordVersion, setRecordVersion] = useState(null);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(!!id);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  const isEdit = !!id;
  const canSave = isEdit ? CMDB_PERMISSIONS.canEditCI(role) : CMDB_PERMISSIONS.canCreateCI(role);

  useEffect(() => {
    let cancelled = false;
    api.get('/cmdb/types/')
      .then((r) => { if (!cancelled) setTypes(safeResults(r.data?.results ?? r.data)); })
      .catch(() => { if (!cancelled) setTypes([]); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;
    setLoading(true); // eslint-disable-line react/set-state-in-effect
    setError(''); // eslint-disable-line react/set-state-in-effect
    api.get(CMDB_API_CONTRACT.ciDetail.endpoint(Number(id)))
      .then((r) => {
        if (cancelled) return;
        const ci = r.data || {};
        const next = { ...EMPTY_FORM };
        Object.keys(EMPTY_FORM).forEach((k) => {
          if (k === 'ci_type') next[k] = ci.ci_type ? String(ci.ci_type) : '';
          else next[k] = ci[k] ?? '';
        });
        setForm(next);
        setRecordVersion(ci.record_version ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(parseApiError(e).global || 'Could not load configuration item.');
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
    setFieldErrors({});
    const payload = toPayload(form);
    if (isEdit && recordVersion != null) payload.expected_record_version = recordVersion;
    try {
      let response;
      if (isEdit) {
        response = await api.patch(CMDB_API_CONTRACT.ciEdit.endpoint(Number(id)), payload);
      } else {
        response = await api.post(CMDB_API_CONTRACT.ciCreate.endpoint, payload);
      }
      const saved = response?.data;
      if (onSaved) onSaved(saved);
      else if (saved?.id) window.location.hash = `#/cmdb/items/${saved.id}`;
      else window.location.hash = '#/cmdb/items';
    } catch (err) {
      const parsed = parseApiError(err);
      setError(parsed.global || 'Could not save configuration item.');
      setFieldErrors(parsed.fields || {});
    } finally {
      setSaving(false);
    }
  };

  if (role === 'employee') {
    return <div className="error-summary" role="alert">You do not have permission to create or edit configuration items.</div>;
  }

  if (loading) return <div className="panel panel-pad"><LoadingRows n={6} /></div>;

  return (
    <div>
      <PageHeader
        title={isEdit ? 'Edit Configuration Item' : 'New Configuration Item'}
        sub={isEdit ? `Update CI #${id}` : 'Create a configuration item in the CMDB'}
        actions={(
          <>
            <a className="btn-small" href={isEdit ? `#/cmdb/items/${id}` : '#/cmdb/items'}>Cancel</a>
          </>
        )}
      />

      {error && <ErrorSummary parsed={{ global: error }} />}

      <form className="panel panel-pad" onSubmit={save} noValidate>
        <div className="split-grid split-2">
          <Field label="CI Name" required error={fieldErrors.name}>
            <Input value={form.name} onChange={(e) => setField('name', e.target.value)} aria-label="CI name" />
          </Field>
          <Field label="CI Type" required error={fieldErrors.ci_type}>
            <Select value={form.ci_type} onChange={(e) => setField('ci_type', e.target.value)} aria-label="CI type">
              <option value="">Select a type</option>
              {types.map((t) => <option key={t.id} value={String(t.id)}>{t.name || t.code || `Type #${t.id}`}</option>)}
            </Select>
          </Field>
        </div>

        <Field label="Description" error={fieldErrors.description}>
          <textarea className="input" rows={4} value={form.description} onChange={(e) => setField('description', e.target.value)} aria-label="Description" />
        </Field>

        <div className="split-grid split-3">
          <Field label="Status" error={fieldErrors.status}>
            <Select value={form.status} onChange={(e) => setField('status', e.target.value)} aria-label="Status">
              {Object.entries(CI_STATUS_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Lifecycle State" error={fieldErrors.lifecycle_state}>
            <Select value={form.lifecycle_state} onChange={(e) => setField('lifecycle_state', e.target.value)} aria-label="Lifecycle state">
              {Object.entries(CI_LIFECYCLE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Criticality" error={fieldErrors.criticality}>
            <Select value={form.criticality} onChange={(e) => setField('criticality', e.target.value)} aria-label="Criticality">
              {Object.entries(CRITICALITY_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
        </div>

        <div className="split-grid split-3">
          <Field label="Environment" error={fieldErrors.environment}>
            <Select value={form.environment} onChange={(e) => setField('environment', e.target.value)} aria-label="Environment">
              {Object.entries(ENVIRONMENT_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Source" error={fieldErrors.source}>
            <Select value={form.source} onChange={(e) => setField('source', e.target.value)} aria-label="Source">
              {Object.entries(SOURCE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Monitoring State" error={fieldErrors.monitoring_state}>
            <Select value={form.monitoring_state} onChange={(e) => setField('monitoring_state', e.target.value)} aria-label="Monitoring state">
              {Object.entries(MONITORING_STATE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
        </div>

        <div className="split-grid split-3">
          <Field label="Data Classification" error={fieldErrors.data_classification}>
            <Select value={form.data_classification} onChange={(e) => setField('data_classification', e.target.value)} aria-label="Data classification">
              {Object.entries(DATA_CLASSIFICATION_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Validated System Impact" error={fieldErrors.validated_system_impact}>
            <Select value={form.validated_system_impact} onChange={(e) => setField('validated_system_impact', e.target.value)} aria-label="Validated system impact">
              {Object.entries(VALIDATED_SYSTEM_IMPACT_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Version" error={fieldErrors.version}>
            <Input value={form.version} onChange={(e) => setField('version', e.target.value)} aria-label="Version" />
          </Field>
        </div>

        <div className="split-grid split-2">
          <Field label="Location" error={fieldErrors.location}><Input value={form.location} onChange={(e) => setField('location', e.target.value)} /></Field>
          <Field label="External Reference" error={fieldErrors.external_reference}><Input value={form.external_reference} onChange={(e) => setField('external_reference', e.target.value)} /></Field>
        </div>
        <div className="split-grid split-3">
          <Field label="Manufacturer" error={fieldErrors.manufacturer}><Input value={form.manufacturer} onChange={(e) => setField('manufacturer', e.target.value)} /></Field>
          <Field label="Model" error={fieldErrors.model}><Input value={form.model} onChange={(e) => setField('model', e.target.value)} /></Field>
          <Field label="Serial Number" error={fieldErrors.serial_number}><Input value={form.serial_number} onChange={(e) => setField('serial_number', e.target.value)} /></Field>
        </div>
        <div className="split-grid split-3">
          <Field label="Hostname" error={fieldErrors.hostname}><Input value={form.hostname} onChange={(e) => setField('hostname', e.target.value)} /></Field>
          <Field label="IP Address" error={fieldErrors.ip_address}><Input value={form.ip_address} onChange={(e) => setField('ip_address', e.target.value)} placeholder="e.g. 10.0.0.10" /></Field>
          <Field label="DNS Name" error={fieldErrors.dns_name}><Input value={form.dns_name} onChange={(e) => setField('dns_name', e.target.value)} /></Field>
        </div>

        <div className="row-end" style={{ marginTop: 20 }}>
          {!canSave && <span className="field-hint">You do not have permission to save configuration items.</span>}
          <button type="submit" className="btn-primary" disabled={!canSave || saving || !form.name || !form.ci_type}>
            {saving ? 'Saving…' : (isEdit ? 'Update CI' : 'Create CI')}
          </button>
          <a className="btn-ghost" href={isEdit ? `#/cmdb/items/${id}` : '#/cmdb/items'}>Cancel</a>
        </div>
      </form>
    </div>
  );
}

