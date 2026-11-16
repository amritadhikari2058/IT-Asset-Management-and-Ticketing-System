import { useEffect, useState } from 'react';
import api from './api';
import { useAuth, useTableColumns } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
  Field, Select, Input, Select as SelectComponent, SelectOption,
  ConfirmDialog, Modal, ErrorSummary, parseApiError,
} from './components';
import {
  formatDate, formatDateTime, formatPercent, ciStatusBadgeVariant,
  criticalityBadgeVariant, safeResults, formatVerificationAge,
  buildCIListUrl, CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS,
  CMDB_ERRORS, STATUS_LABELS, LIFECYCLE_LABELS, CRITICALITY_LABELS,
  ENV_LABELS, SOURCE_LABELS, MONITORING_LABELS, DATA_CLASS_LABELS,
  IMPACT_LABELS, RELATIONSHIP_TYPE_LABELS, RELATIONSHIP_STATUS_LABELS,
} from './cmdb-utils';

// ── CI Type schema-driven attribute types ─────────────────────────────
const SAFE_ATTRIBUTE_TYPES = ['text', 'number', 'boolean', 'date', 'datetime',
  'choice', 'multichoice', 'url', 'ip_address'];

function isSafeAttributeType(type) {
  return SAFE_ATTRIBUTE_TYPES.includes(type);
}

// ── CI Form component ──────────────────────────────────────────────────

export function CiForm({ ciId = null }) {
  const { role } = useAuth();
  const [form, setForm] = useState({
    name: '',
    ci_type: null,
    description: '',
    status: 'planned',
    lifecycle_state: 'proposed',
    criticality: 'medium',
    environment: 'production',
    asset: null,
    software_product: null,
    service_catalogue_item: null,
    department: null,
    location: '',
    owner: null,
    technical_owner: null,
    support_group: null,
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
    source_identifier: '',
    attributes: {},
  });

  const [ciTypeOptions, setCiTypeOptions] = useState([]);
  const [loadingCiTypes, setLoadingCiTypes] = useState(true);
  const [attributesSchema, setAttributesSchema] = useState({});
  const [attributeErrors, setAttributeErrors] = useState({});
  const [isEdit, setIsEdit] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Load CI types from backend
  useEffect(() => {
    let cancelled = false;
    setLoadingCiTypes(true);
    api.get(CMDB_API_CONTRACT.typesList.endpoint)
      .then((r) => { if (!cancelled) setCiTypeOptions(r.data); })
      .catch((e) => setError('Could not load CI types.'))
      .finally(() => { if (!cancelled) setLoadingCiTypes(false); });
    return () => { cancelled = true; };
  }, []);

  // If editing, load the CI data
  useEffect(() => {
    if (ciId && !isEdit) {
      let cancelled = false;
      setSaving(true);
      api.get(`${CMDB_API_CONTRACT.ciDetail.endpoint(ciId)}`)
        .then((r) => {
          if (cancelled) return;
          const ci = r.data;
          setForm({
            name: ci.name,
            ci_type: ci.ci_type ? (typeof ci.ci_type === 'object' ? ci.ci_type.id : ci.ci_type) : null,
            description: ci.description || '',
            status: ci.status || 'planned',
            lifecycle_state: ci.lifecycle_state || 'proposed',
            criticality: ci.criticality || 'medium',
            environment: ci.environment || 'production',
            asset: ci.asset ? ci.asset.id : null,
            software_product: ci.software_product ? ci.software_product.id : null,
            service_catalogue_item: ci.service_catalogue_item ? ci.service_catalogue_item.id : null,
            department: ci.department ? ci.department.id : null,
            location: ci.location || '',
            owner: ci.owner ? ci.owner.id : null,
            technical_owner: ci.technical_owner ? ci.technical_owner.id : null,
            support_group: ci.support_group ? ci.support_group.id : null,
            vendor: ci.vendor || '',
            manufacturer: ci.manufacturer || '',
            model: ci.model || '',
            serial_number: ci.serial_number || '',
            version: ci.version || '',
            hostname: ci.hostname || '',
            ip_address: ci.ip_address || '',
            dns_name: ci.dns_name || '',
            external_reference: ci.external_reference || '',
            source: ci.source || 'manual',
            source_identifier: ci.source_identifier || '',
            attributes: ci.attributes || {},
          });
          setIsEdit(true);
        })
        .catch((e) => {
          const parsed = parseApiError(e);
          setError(parsed.global || 'Could not load CI.');
        })
        .finally(() => { if (cancelled) setSaving(false); });
      return () => { cancelled = true; });
    }
  }, [ciId]);

  // When CI type changes, fetch the schema for dynamic attributes
  useEffect(() => {
    const selectedType = ciTypeOptions.find((t) => t.id === form.ci_type);
    if (selectedType && selectedType.schema) {
      setAttributesSchema(selectedType.schema);
    } else {
      setAttributesSchema({});
    }
  }, [form.ci_type, ciTypeOptions]);

  // Save CI (create or update)
  const saveCi = async () => {
    setError('');
    setAttributeErrors({});
    setSaving(true);

    // Validate required attributes from schema
    const validatedAttrs = {};
    if (attributesSchema && typeof attributesSchema === 'object') {
      for (const [key, def] of Object.entries(attributesSchema)) {
        if (def.required && (!form.attributes || !form.attributes[key])) {
          setAttributeErrors({ ...attributeErrors, [key]: `Required field: ${def.label || key}` });
          continue;
        }
        if (form.attributes && form.attributes[key] !== undefined) {
          validatedAttrs[key] = form.attributes[key];
        }
      }
    }

    const payload = {
      name: form.name,
      ci_type: form.ci_type,
      description: form.description,
      status: form.status,
      lifecycle_state: form.lifecycle_state,
      criticality: form.criticality,
      environment: form.environment,
      asset: form.asset || null,
      software_product: form.software_product || null,
      service_catalogue_item: form.service_catalogue_item || null,
      department: form.department || null,
      location: form.location,
      owner: form.owner || null,
      technical_owner: form.technical_owner || null,
      support_group: form.support_group || null,
      vendor: form.vendor,
      manufacturer: form.manufacturer,
      model: form.model,
      serial_number: form.serial_number,
      version: form.version,
      hostname: form.hostname,
      ip_address: form.ip_address,
      dns_name: form.dns_name,
      external_reference: form.external_reference,
      attributes: Object.keys(validatedAttrs).length > 0 ? validatedAttrs : form.attributes,
      source: form.source,
      source_identifier: form.source_identifier,
    };

    try {
      let response;
      if (isEdit && ciId) {
        response = await api.patch(CMDB_API_CONTRACT.ciEdit.endpoint(ciId), payload);
      } else {
        response = await api.post(CMDB_API_CONTRACT.ciCreate.endpoint, payload);
      }
      setError('');
      window.location.hash = `#/cmdb/items/${response.id || ciId}`;
    } catch (e) {
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not save CI.');
      setAttributeErrors(parsed.fields || {});
    } finally {
      setSaving(false);
    }
  };

  // Cancel/close
  const handleCancel = () => {
    window.location.hash = `#/cmdb/items`;
  };

  // Validate form before save
  const canSave = () => {
    const hasName = form.name && form.name.trim().length > 0;
    const hasType = form.ci_type !== null;
    const hasNoErrors = Object.keys(attributeErrors).length === 0;
    return hasName && hasType && hasNoErrors;
  };

  // Disable employee access
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees cannot create or edit CIs.
      </div>
    );
  }

  if (loadingCiTypes && !isEdit) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading CI types...</p>
      </div>
    );
  }

  if (isEdit && error && !saving) {
    return (
      <div className="error-summary" role="alert">
        {error}
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={isEdit ? `Edit CI` : `New CI`}
        sub={isEdit ? `CI ID: ${form.ci_number || ciId}` : 'Fill in the CI details below'}
        actions={}
      />

      {error && <ErrorSummary parsed={{ global: error }} />}

      <Form rowGutters={16}>
        <Field label="CI Name *">
          <Input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="e.g. Core Authentication Server"
            disabled={saving}
          />
          {form.name && form.name.length > 0 && !canSave() && (
            <span className="field-hint">Missing criticality or CI type</span>
          )}
        </Field>

        <Field label="CI Type *">
          <SelectComponent
            value={form.ci_type ?? ''}
            onChange={(e) => setForm({ ...form, ci_type: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="CI Type"
          >
            <SelectOption value="">Select a CI Type</SelectOption>
            {ciTypeOptions.map((t) => (
              <SelectOption key={t.id} value={t.id}>{t.name}</SelectOption>
            ))}
          </SelectComponent>
          {form.ci_type && !canSave() && (
            <span className="field-hint">Required field</span>
          )}
        </Field>

        <Field label="Description">
          <Input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            type="textarea"
            placeholder="Optional description"
            disabled={saving}
          />
        </Field>

        <Field label="Status *">
          <SelectComponent
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value })}
            disabled={saving}
            aria-label="Status"
          >
            <SelectOption value="planned">Planned</SelectOption>
            <SelectOption value="active">Active</SelectOption>
            <SelectOption value="inactive">Inactive</SelectOption>
            <SelectOption value="maintenance">Maintenance</SelectOption>
            <SelectOption value="degraded">Degraded</SelectOption>
            <SelectOption value="failed">Failed</SelectOption>
            <SelectOption value="retired">Retired</SelectOption>
            <SelectOption value="disposed">Disposed</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Lifecycle State *">
          <SelectComponent
            value={form.lifecycle_state}
            onChange={(e) => setForm({ ...form, lifecycle_state: e.target.value })}
            disabled={saving}
            aria-label="Lifecycle State"
          >
            <SelectOption value="proposed">Proposed</SelectOption>
            <SelectOption value="ordered">Ordered</SelectOption>
            <SelectOption value="received">Received</SelectOption>
            <SelectOption value="installed">Installed</SelectOption>
            <SelectOption value="operational">Operational</SelectOption>
            <SelectOption value="under_change">Under Change</SelectOption>
            <SelectOption value="retired">Retired</SelectOption>
            <SelectOption value="disposed">Disposed</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Criticality *">
          <SelectComponent
            value={form.criticality}
            onChange={(e) => setForm({ ...form, criticality: e.target.value })}
            disabled={saving}
            aria-label="Criticality"
          >
            <SelectOption value="low">Low</SelectOption>
            <SelectOption value="medium">Medium</SelectOption>
            <SelectOption value="high">High</SelectOption>
            <SelectOption value="critical">Critical</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Environment *">
          <SelectComponent
            value={form.environment}
            onChange={(e) => setForm({ ...form, environment: e.target.value })}
            disabled={saving}
            aria-label="Environment"
          >
            <SelectOption value="development">Development</SelectOption>
            <SelectOption value="test">Test</SelectOption>
            <SelectOption value="staging">Staging</SelectOption>
            <SelectOption value="production">Production</SelectOption>
            <SelectOption value="disaster_recovery">Disaster Recovery</SelectOption>
            <SelectOption value="office">Office</SelectOption>
            <SelectOption value="other">Other</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Asset (optional)">
          <SelectComponent
            value={form.asset != null ? String(form.asset) : ''}
            onChange={(e) => setForm({ ...form, asset: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Related asset"
          >
            <SelectOption value="">No asset</SelectOption>
            {/* Asset options would be loaded from API */}
          </SelectComponent>
        </Field>

        <Field label="Software Product (optional)">
          <SelectComponent
            value={form.software_product != null ? String(form.software_product) : ''}
            onChange={(e) => setForm({ ...form, software_product: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Related software product"
          >
            <SelectOption value="">No software product</SelectOption>
            {/* Software product options would be loaded from API */}
          </SelectComponent>
        </Field>

        <Field label="Service (optional)">
          <SelectComponent
            value={form.service_catalogue_item != null ? String(form.service_catalogue_item) : ''}
            onChange={(e) => setForm({ ...form, service_catalogue_item: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Related service"
          >
            <SelectOption value="">No service</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Department (optional)">
          <SelectComponent
            value={form.department != null ? String(form.department) : ''}
            onChange={(e) => setForm({ ...form, department: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Department"
          >
            <SelectOption value="">Select department</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Location *">
          <Input
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            placeholder="e.g. Data Center 1, Rack A"
            disabled={saving}
            aria-label="Location"
          />
        </Field>

        <Field label="Owner (optional)">
          <SelectComponent
            value={form.owner != null ? String(form.owner) : ''}
            onChange={(e) => setForm({ ...form, owner: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Owner"
          >
            <SelectOption value="">Unassigned</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Technical Owner (optional)">
          <SelectComponent
            value={form.technical_owner != null ? String(form.technical_owner) : ''}
            onChange={(e) => setForm({ ...form, technical_owner: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Technical Owner"
          >
            <SelectOption value="">Unassigned</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Support Group (optional)">
          <SelectComponent
            value={form.support_group != null ? String(form.support_group) : ''}
            onChange={(e) => setForm({ ...form, support_group: e.target.value ? Number(e.target.value) : null })}
            disabled={saving}
            aria-label="Support Group"
          >
            <SelectOption value="">Select group</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Vendor *">
          <Input
            value={form.vendor}
            onChange={(e) => setForm({ ...form, vendor: e.target.value })}
            placeholder="e.g. Dell, HPE, IBM"
            disabled={saving}
            aria-label="Vendor"
          />
        </Field>

        <Field label="Manufacturer">
          <Input
            value={form.manufacturer}
            onChange={(e) => setForm({ ...form, manufacturer: e.target.value })}
            placeholder="e.g. Dell Inc., HPE"
            disabled={saving}
            aria-label="Manufacturer"
          />
        </Field>

        <Field label="Model">
          <Input
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            placeholder="e.g. PowerEdge R750"
            disabled={saving}
            aria-label="Model"
          />
        </Field>

        <Field label="Serial Number">
          <Input
            value={form.serial_number}
            onChange={(e) => setForm({ ...form, serial_number: e.target.value })}
            placeholder="e.g. CNU12345678"
            disabled={saving}
            aria-label="Serial Number"
          />
        </Field>

        <Field label="Version">
          <Input
            value={form.version}
            onChange={(e) => setForm({ ...form, version: e.target.value })}
            placeholder="e.g. 1.0.0"
            disabled={saving}
            aria-label="Version"
          />
        </Field>

        <Field label="Hostname">
          <Input
            value={form.hostname}
            onChange={(e) => setForm({ ...form, hostname: e.target.value })}
            placeholder="e.g. auth-server01"
            disabled={saving}
            aria-label="Hostname"
          />
        </Field>

        <Field label="IP Address">
          <Input
            value={form.ip_address}
            onChange={(e) => setForm({ ...form, ip_address: e.target.value })}
            placeholder="e.g. 192.168.1.10"
            disabled={saving}
            aria-label="IP Address"
          />
        </Field>

        <Field label="DNS Name">
          <Input
            value={form.dns_name}
            onChange={(e) => setForm({ ...form, dns_name: e.target.value })}
            placeholder="e.g. auth-server01.example.com"
            disabled={saving}
            aria-label="DNS Name"
          />
        </Field>

        <Field label="External Reference">
          <Input
            value={form.external_reference}
            onChange={(e) => setForm({ ...form, external_reference: e.target.value })}
            placeholder="e.g. ticket-123, asset-LT-001"
            disabled={saving}
            aria-label="External Reference"
          />
        </Field>

        <Field label="Source *">
          <SelectComponent
            value={form.source}
            onChange={(e) => setForm({ ...form, source: e.target.value })}
            disabled={saving}
            aria-label="Source"
          >
            <SelectOption value="manual">Manual</SelectOption>
            <SelectOption value="asset_sync">Asset Sync</SelectOption>
            <SelectOption value="licensing_sync">Licensing Sync</SelectOption>
            <SelectOption value="discovery">Discovery</SelectOption>
            <SelectOption value="import">Import</SelectOption>
            <SelectOption value="integration">Integration</SelectOption>
          </SelectComponent>
        </Field>

        <Field label="Verified-System Impact *">
          <SelectComponent
            value={form.validated_system_impact || 'none'}
            onChange={(e) => setForm({ ...form, validated_system_impact: e.target.value })}
            disabled={saving}
            aria-label="Validated-System Impact"
          >
            <SelectOption value="none">None</SelectOption>
            <SelectOption value="documentation_only">Documentation Only</SelectOption>
            <SelectOption value="configuration">Configuration</SelectOption>
            <SelectOption value="data_integrity_impact">Data Integrity Impact</SelectOption>
          </SelectComponent>
        </Field>

        {/* Dynamic attributes from CI Type schema */}
        {Object.keys(attributesSchema).length > 0 && !saving && (
          <Field label="Dynamic Attributes">
            <p className="muted small">
              Schema-driven attributes for {attributesSchema.name || 'this CI Type'}
            </p>
            <div className="attributes-grid">
              {Object.entries(attributesSchema).map(([key, def]) => {
                if (!isSafeAttributeType(def.type)) return null;
                const value = form.attributes && form.attributes[key] !== undefined
                  ? String(form.attributes[key])
                  : def.default !== undefined ? String(def.default) : '';
                const label = def.label || key;
                const help = def.help_text || '';
                return (
                  <div key={key} className="attribute-row" style={{ marginBottom: 12, paddingBottom: 12, borderBottom: '1px solid #dee2e6' }}>
                    <div className="attribute-row-left">
                      <span className="attribute-row-label">{label}</span>
                      {def.required && <span className="required-mark"> *</span>}
                    </div>
                    <div className="attribute-row-right">
                      if (def.type === 'boolean') {
                        return (
                          <SelectComponent
                            value={form.attributes[key] === true ? 'true' : form.attributes[key] === false ? 'false' : 'false'}
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = e.target.value === 'true';
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            aria-label={label}
                          >
                            <SelectOption value="true">Yes</SelectOption>
                            <SelectOption value="false">No</SelectOption>
                          </SelectComponent>
                        );
                      } else if (def.type === 'number') {
                        return (
                          <Input
                            type="number"
                            value={value || ''}
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = e.target.value === '' ? undefined : Number(e.target.value);
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            placeholder={def.placeholder || '0'}
                            aria-label={label}
                          />
                        );
                      } else if (def.type === 'choice' && def.choices) {
                        return (
                          <SelectComponent
                            value={value || (def.choices[0] ? def.choices[0][0] : '')}
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = e.target.value;
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            aria-label={label}
                          >
                            {def.choices.map(([v, l]) => (
                              <SelectOption key={v} value={v}>{l}</SelectOption>
                            ))}
                          </SelectComponent>
                        );
                      } else if (def.type === 'multichoice' && def.choices) {
                        const selected = value ? value.split(',') : [];
                        return (
                          <SelectComponent
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = Array.from(e.target.options)
                                .filter((o) => o.selected)
                                .map((o) => o.value)
                                .join(',');
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            aria-label={label}
                          >
                            {def.choices.map(([v, l]) => (
                              <SelectOption key={v} value={v} selected={selected.includes(v)}>
                                {l}
                              </SelectOption>
                            ))}
                          </SelectComponent>
                        );
                      } else if (def.type === 'url') {
                        return (
                          <Input
                            type="url"
                            value={value || ''}
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = e.target.value || undefined;
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            placeholder="https://example.com"
                            aria-label={label}
                          />
                        );
                      } else if (def.type === 'ip_address') {
                        return (
                          <Input
                            type="text"
                            value={value || ''}
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = e.target.value || undefined;
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            placeholder="192.168.1.1"
                            aria-label={label}
                          />
                        );
                      } else { // text or default
                        return (
                          <Input
                            value={value || ''}
                            onChange={(e) => {
                              const newAttrs = { ...form.attributes };
                              newAttrs[key] = e.target.value || undefined;
                              setForm({ ...form, attributes: newAttrs });
                            }}
                            placeholder={def.placeholder || ''}
                            aria-label={label}
                          />
                        }
                      })
                );
              })}
            </div>
          </Field>
        )}

        {/* Form actions */}
        <div className="row-end" style={{ marginTop: 20 }}>
          {saving ? (
            <button type="button" className="btn-primary" disabled={saving}>
              Saving…
            </button>
          ) : (
            <>
              {!canSave() && (
                <span className="field-hint">Complete all required fields.</span>
              ) &&
              <button
                type="submit"
                className="btn-primary"
                onClick={saveCi}
                disabled={!canSave() || saving}
              >
                {isEdit ? 'Update CI' : 'Create CI'}
              </button>}
              <button
                type="button"
                className="btn-ghost"
                onClick={handleCancel}
                disabled={saving}
              >
                Cancel
              </button>
            </>
          )}
        </div>
      </Form>
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