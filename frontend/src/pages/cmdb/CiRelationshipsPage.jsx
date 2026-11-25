import { useEffect, useMemo, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import { ConfirmDialog, DataTable, EmptyState, Field, Input, LoadingRows, PageHeader, Pager, Select } from '../../components';
import { parseApiError } from '../../api-utils';
import {
  RELATIONSHIP_CONFIDENCE_LABELS,
  RELATIONSHIP_STATUS_LABELS,
  RELATIONSHIP_TYPE_LABELS,
  formatDateTime,
  safeResults,
} from '../../shared/cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS } from '../../shared/cmdb';

const EMPTY_FORM = {
  direction: 'outgoing',
  related_ci: '',
  relationship_type: '',
  description: '',
  confidence: 'confirmed',
  status: 'active',
};

const EMPTY_GLOBAL_FILTERS = {
  search: '',
  source_ci: '',
  target_ci: '',
  ci_type: '',
  relationship_type: '',
  status: '',
};

function ciDisplay(ci) {
  if (!ci) return '—';
  const num = ci.ci_number || `CI #${ci.id}`;
  return ci.name ? `${num} — ${ci.name}` : num;
}

export function GlobalRelationshipsPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [relationships, setRelationships] = useState([]);
  const [ciOptions, setCiOptions] = useState([]);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [filters, setFilters] = useState(EMPTY_GLOBAL_FILTERS);
  const [applied, setApplied] = useState(EMPTY_GLOBAL_FILTERS);
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState(null);

  const canManage = CMDB_PERMISSIONS.canCreateRelationship(role) || CMDB_PERMISSIONS.canEditRelationship(role);
  const canDelete = CMDB_PERMISSIONS.canDeleteRelationship(role);
  const pageSize = 25;

  const ciById = useMemo(() => {
    const map = new Map();
    ciOptions.forEach((ci) => map.set(Number(ci.id), ci));
    return map;
  }, [ciOptions]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (applied.source_ci) params.set('source_ci', applied.source_ci);
      if (applied.target_ci) params.set('target_ci', applied.target_ci);
      if (applied.relationship_type) params.set('relationship_type', applied.relationship_type);
      if (applied.status) params.set('status', applied.status);
      if (applied.search) params.set('search', applied.search);
      const qs = params.toString();
      const [relRes, ciRes, typeRes] = await Promise.all([
        api.get(`/cmdb/relationships/${qs ? `?${qs}` : ''}`),
        api.get('/cmdb/items/?page_size=500'),
        api.get('/cmdb/types/'),
      ]);
      setRelationships(safeResults(relRes.data?.results ?? relRes.data));
      setCiOptions(safeResults(ciRes.data?.results ?? ciRes.data));
      setTypes(safeResults(typeRes.data?.results ?? typeRes.data));
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load relationships.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await load();
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applied]);

  const filtered = useMemo(() => {
    const q = (applied.search || '').trim().toLowerCase();
    const typeId = applied.ci_type ? Number(applied.ci_type) : null;
    return relationships.filter((rel) => {
      const src = ciById.get(Number(rel.source_ci));
      const tgt = ciById.get(Number(rel.target_ci));
      if (applied.source_ci && Number(rel.source_ci) !== Number(applied.source_ci)) return false;
      if (applied.target_ci && Number(rel.target_ci) !== Number(applied.target_ci)) return false;
      if (applied.relationship_type && rel.relationship_type !== applied.relationship_type) return false;
      if (applied.status && rel.status !== applied.status) return false;
      if (typeId) {
        const srcType = src?.ci_type ?? src?.ci_type_id;
        const tgtType = tgt?.ci_type ?? tgt?.ci_type_id;
        if (Number(srcType) !== typeId && Number(tgtType) !== typeId) return false;
      }
      if (q) {
        const hay = [
          rel.id, rel.source_ci, rel.target_ci, rel.source_ci_number, rel.target_ci_number,
          rel.relationship_type, rel.status, rel.description, rel.confidence, rel.source,
          src?.name, src?.ci_number, tgt?.name, tgt?.ci_number,
        ].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [relationships, applied, ciById]);

  useEffect(() => { setPage(1); }, [applied]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageRows = filtered.slice((page - 1) * pageSize, page * pageSize);

  const submitFilters = (e) => {
    e.preventDefault();
    setApplied({ ...filters });
  };

  const resetFilters = () => {
    setFilters(EMPTY_GLOBAL_FILTERS);
    setApplied(EMPTY_GLOBAL_FILTERS);
  };

  const runAction = async (row, action) => {
    setBusyId(row.id);
    setError('');
    setMsg('');
    try {
      if (action === 'activate') await api.post(`/cmdb/relationships/${row.id}/activate/`, {});
      if (action === 'deactivate') await api.post(`/cmdb/relationships/${row.id}/deactivate/`, {});
      if (action === 'delete') await api.delete(`/cmdb/relationships/${row.id}/`);
      setMsg(action === 'delete' ? 'Relationship removed.' : `Relationship ${action}d.`);
      await load();
    } catch (err) {
      setError(parseApiError(err).global || 'Relationship action failed.');
    } finally {
      setBusyId(null);
      setConfirm(null);
    }
  };

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no CMDB relationship access.</div>;
  }

  return (
    <div>
      <PageHeader
        title="CI Relationships"
        sub="Browse and manage relationships across configuration items"
        actions={<a className="btn-small" href="#/cmdb/items">Configuration Items</a>}
      />

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <form onSubmit={submitFilters} noValidate>
          <div className="split-grid split-4">
            <Field label="Search">
              <Input value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))} placeholder="CI name/number, description…" />
            </Field>
            <Field label="Source CI">
              <Select value={filters.source_ci} onChange={(e) => setFilters((f) => ({ ...f, source_ci: e.target.value }))}>
                <option value="">All source CIs</option>
                {ciOptions.map((ci) => <option key={ci.id} value={String(ci.id)}>{ciDisplay(ci)}</option>)}
              </Select>
            </Field>
            <Field label="Target CI">
              <Select value={filters.target_ci} onChange={(e) => setFilters((f) => ({ ...f, target_ci: e.target.value }))}>
                <option value="">All target CIs</option>
                {ciOptions.map((ci) => <option key={ci.id} value={String(ci.id)}>{ciDisplay(ci)}</option>)}
              </Select>
            </Field>
            <Field label="CI Type (source or target)">
              <Select value={filters.ci_type} onChange={(e) => setFilters((f) => ({ ...f, ci_type: e.target.value }))}>
                <option value="">All types</option>
                {types.map((t) => <option key={t.id} value={String(t.id)}>{t.name || t.code || `Type #${t.id}`}</option>)}
              </Select>
            </Field>
          </div>
          <div className="split-grid split-4" style={{ marginTop: 12 }}>
            <Field label="Relationship Type">
              <Select value={filters.relationship_type} onChange={(e) => setFilters((f) => ({ ...f, relationship_type: e.target.value }))}>
                <option value="">All relationship types</option>
                {Object.entries(RELATIONSHIP_TYPE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </Select>
            </Field>
            <Field label="Status">
              <Select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
                <option value="">All statuses</option>
                {Object.entries(RELATIONSHIP_STATUS_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </Select>
            </Field>
            <div />
            <div className="row-end" style={{ alignItems: 'flex-end' }}>
              <button type="submit" className="btn-primary">Apply</button>
              <button type="button" className="btn-small" onClick={resetFilters}>Reset</button>
            </div>
          </div>
        </form>
      </div>

      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-banner" role="status">{msg}</div>}

      <div className="panel panel-pad">
        {loading ? (
          <LoadingRows n={6} />
        ) : filtered.length === 0 ? (
          <EmptyState title="No relationships found." hint="Adjust filters or create relationships from a configuration item detail page." />
        ) : (
          <>
            <p className="muted" style={{ marginTop: 0 }}>{filtered.length} relationship{filtered.length === 1 ? '' : 's'} found. Direction is <strong>source → target</strong>.</p>
            <DataTable
              columns={[
                {
                  key: 'source',
                  label: 'Source CI',
                  render: (row) => {
                    const src = ciById.get(Number(row.source_ci));
                    return <a href={`#/cmdb/items/${row.source_ci}`}>{ciDisplay(src) || row.source_ci_number || `CI #${row.source_ci}`}</a>;
                  },
                },
                { key: 'direction', label: 'Direction', render: () => '→' },
                {
                  key: 'target',
                  label: 'Target CI',
                  render: (row) => {
                    const tgt = ciById.get(Number(row.target_ci));
                    return <a href={`#/cmdb/items/${row.target_ci}`}>{ciDisplay(tgt) || row.target_ci_number || `CI #${row.target_ci}`}</a>;
                  },
                },
                { key: 'relationship_type', label: 'Type', render: (row) => RELATIONSHIP_TYPE_LABELS[row.relationship_type] || row.relationship_type || '—' },
                { key: 'status', label: 'Status', render: (row) => RELATIONSHIP_STATUS_LABELS[row.status] || row.status || '—' },
                { key: 'confidence', label: 'Confidence', render: (row) => RELATIONSHIP_CONFIDENCE_LABELS[row.confidence] || row.confidence || '—' },
                { key: 'description', label: 'Description / Metadata', render: (row) => row.description || '—' },
                { key: 'source_attr', label: 'Source', render: (row) => row.source || (row.discovered ? 'Discovered' : '—') },
                { key: 'updated_at', label: 'Updated', render: (row) => formatDateTime(row.updated_at || row.created_at) },
                {
                  key: 'actions',
                  label: 'Actions',
                  render: (row) => (
                    <div className="table-actions">
                      <a className="btn-small" href={`#/cmdb/items/${row.source_ci}`}>Open Source</a>
                      <a className="btn-small" href={`#/cmdb/items/${row.target_ci}`}>Open Target</a>
                      <a className="btn-small" href={`#/cmdb/items/${row.source_ci}/relationships`}>Manage</a>
                      {canManage && row.status !== 'active' && (
                        <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'activate')}>Activate</button>
                      )}
                      {canManage && row.status === 'active' && (
                        <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'deactivate')}>Deactivate</button>
                      )}
                      {canDelete && (
                        <button type="button" className="btn-danger" disabled={busyId === row.id} onClick={() => setConfirm({ action: 'delete', row })}>Remove</button>
                      )}
                    </div>
                  ),
                },
              ]}
              rows={pageRows}
              keyOf={(row) => row.id}
              emptyTitle="No relationships found."
              emptyHint="Adjust filters or create relationships from a configuration item detail page."
            />
            <Pager page={page} total={totalPages} count={filtered.length} pageSize={pageSize} onPage={setPage} />
          </>
        )}
      </div>

      {confirm && (
        <ConfirmDialog
          open
          title="Remove relationship"
          message={`Remove relationship ${confirm.row?.source_ci_number || confirm.row?.source_ci} → ${confirm.row?.target_ci_number || confirm.row?.target_ci}? This cannot be undone.`}
          confirmLabel="Remove"
          onCancel={() => setConfirm(null)}
          onConfirm={() => runAction(confirm.row, confirm.action)}
        />
      )}
    </div>
  );
}

export function CiRelationshipsPage({ id: idProp, match }) {
  const id = Number(idProp ?? match?.params?.id);
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [ci, setCi] = useState(null);
  const [relationships, setRelationships] = useState([]);
  const [ciOptions, setCiOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [confirm, setConfirm] = useState(null);

  const canManage = CMDB_PERMISSIONS.canCreateRelationship(role) || CMDB_PERMISSIONS.canEditRelationship(role);
  const canDelete = CMDB_PERMISSIONS.canDeleteRelationship(role);

  const load = async (cancelledRef = { current: false }) => {
    if (!id) return;
    setLoading(true);
    setError('');
    try {
      const [ciRes, relRes, listRes] = await Promise.all([
        api.get(CMDB_API_CONTRACT.ciDetail.endpoint(id)),
        api.get(`/cmdb/relationships/?ci=${id}`),
        api.get('/cmdb/items/?page_size=200'),
      ]);
      if (cancelledRef.current) return;
      setCi(ciRes.data || null);
      setRelationships(safeResults(relRes.data?.results ?? relRes.data));
      setCiOptions(safeResults(listRes.data?.results ?? listRes.data).filter((row) => Number(row.id) !== id));
    } catch (e) {
      if (!cancelledRef.current) setError(parseApiError(e).global || 'Could not load relationships.');
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    const cancelledRef = { current: false };
    load(cancelledRef); // eslint-disable-line react/set-state-in-effect
    return () => { cancelledRef.current = true; };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const grouped = useMemo(() => {
    const outgoing = relationships.filter((r) => Number(r.source_ci) === id);
    const incoming = relationships.filter((r) => Number(r.target_ci) === id);
    return { outgoing, incoming };
  }, [relationships, id]);

  const relatedLabel = (row, direction) => {
    const otherId = direction === 'outgoing' ? row.target_ci : row.source_ci;
    const otherNumber = direction === 'outgoing' ? row.target_ci_number : row.source_ci_number;
    const ciName = ciOptions.find((c) => Number(c.id) === Number(otherId))?.name;
    const parts = [otherNumber || `CI #${otherId}`];
    if (ciName) parts.push(ciName);
    return parts.join(' — ');
  };

  const createRelationship = async (e) => {
    e.preventDefault();
    if (!canManage || !form.related_ci || !form.relationship_type) return;
    setSaving(true);
    setError('');
    setMsg('');
    const payload = {
      source_ci: form.direction === 'outgoing' ? id : Number(form.related_ci),
      target_ci: form.direction === 'outgoing' ? Number(form.related_ci) : id,
      relationship_type: form.relationship_type,
      description: form.description || '',
      confidence: form.confidence,
      status: form.status,
    };
    try {
      await api.post(CMDB_API_CONTRACT.relationshipCreate.endpoint, payload);
      setForm(EMPTY_FORM);
      setMsg('Relationship saved.');
      await load();
    } catch (err) {
      setError(parseApiError(err).global || 'Could not create relationship.');
    } finally {
      setSaving(false);
    }
  };

  const runAction = async (row, action) => {
    setBusyId(row.id);
    setError('');
    setMsg('');
    try {
      if (action === 'activate') await api.post(`/cmdb/relationships/${row.id}/activate/`, {});
      if (action === 'deactivate') await api.post(`/cmdb/relationships/${row.id}/deactivate/`, {});
      if (action === 'delete') await api.delete(`/cmdb/relationships/${row.id}/`);
      setMsg(action === 'delete' ? 'Relationship removed.' : `Relationship ${action}d.`);
      await load();
    } catch (err) {
      setError(parseApiError(err).global || 'Relationship action failed.');
    } finally {
      setBusyId(null);
      setConfirm(null);
    }
  };

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no CMDB relationship access.</div>;
  }
  if (loading && !ci) return <div className="panel panel-pad"><LoadingRows n={6} /></div>;

  const table = (rows, direction) => (
    <DataTable
      columns={[
        {
          key: 'related',
          label: direction === 'outgoing' ? 'Target CI' : 'Source CI',
          render: (row) => {
            const otherId = direction === 'outgoing' ? row.target_ci : row.source_ci;
            return <a href={`#/cmdb/items/${otherId}`}>{relatedLabel(row, direction)}</a>;
          },
        },
        { key: 'relationship_type', label: 'Type', render: (row) => RELATIONSHIP_TYPE_LABELS[row.relationship_type] || row.relationship_type || '—' },
        { key: 'status', label: 'Status', render: (row) => RELATIONSHIP_STATUS_LABELS[row.status] || row.status || '—' },
        { key: 'confidence', label: 'Confidence', render: (row) => RELATIONSHIP_CONFIDENCE_LABELS[row.confidence] || row.confidence || '—' },
        { key: 'description', label: 'Description', render: (row) => row.description || '—' },
        { key: 'updated_at', label: 'Updated', render: (row) => formatDateTime(row.updated_at || row.created_at) },
        {
          key: 'actions',
          label: 'Actions',
          render: (row) => (
            <div className="table-actions">
              <a className="btn-small" href={`#/cmdb/items/${direction === 'outgoing' ? row.target_ci : row.source_ci}`}>Open CI</a>
              {canManage && row.status !== 'active' && (
                <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'activate')}>Activate</button>
              )}
              {canManage && row.status === 'active' && (
                <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'deactivate')}>Deactivate</button>
              )}
              {canDelete && (
                <button type="button" className="btn-danger" disabled={busyId === row.id} onClick={() => setConfirm({ action: 'delete', row })}>Remove</button>
              )}
            </div>
          ),
        },
      ]}
      rows={rows}
      keyOf={(row) => row.id}
      emptyTitle="No relationships found."
      emptyHint={direction === 'outgoing' ? 'No outgoing relationships for this CI.' : 'No incoming relationships for this CI.'}
    />
  );

  return (
    <div>
      <PageHeader
        title={`Relationships · ${ci?.ci_number || `CI #${id}`}`}
        sub={ci?.name || 'Manage CI relationships'}
        actions={(
          <>
            <a className="btn-small" href={`#/cmdb/items/${id}`}>Back to CI</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/dependencies`}>Dependencies</a>
            <a className="btn-small" href={`#/cmdb/items/${id}/impact`}>Impact</a>
          </>
        )}
      />

      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-banner" role="status">{msg}</div>}

      {canManage && (
        <div className="panel panel-pad" style={{ marginBottom: 16 }}>
          <h2 style={{ marginTop: 0 }}>Add Relationship</h2>
          <form onSubmit={createRelationship} noValidate>
            <div className="split-grid split-3">
              <Field label="Direction" required>
                <Select value={form.direction} onChange={(e) => setForm((f) => ({ ...f, direction: e.target.value }))}>
                  <option value="outgoing">Outgoing (this CI → related CI)</option>
                  <option value="incoming">Incoming (related CI → this CI)</option>
                </Select>
              </Field>
              <Field label="Related CI" required>
                <Select value={form.related_ci} onChange={(e) => setForm((f) => ({ ...f, related_ci: e.target.value }))}>
                  <option value="">Select CI</option>
                  {ciOptions.map((option) => (
                    <option key={option.id} value={String(option.id)}>
                      {option.ci_number ? `${option.ci_number} — ` : ''}{option.name || `CI #${option.id}`}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Relationship Type" required>
                <Select value={form.relationship_type} onChange={(e) => setForm((f) => ({ ...f, relationship_type: e.target.value }))}>
                  <option value="">Select type</option>
                  {Object.entries(RELATIONSHIP_TYPE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </Select>
              </Field>
            </div>
            <div className="split-grid split-3">
              <Field label="Status">
                <Select value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                  {Object.entries(RELATIONSHIP_STATUS_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </Select>
              </Field>
              <Field label="Confidence">
                <Select value={form.confidence} onChange={(e) => setForm((f) => ({ ...f, confidence: e.target.value }))}>
                  {Object.entries(RELATIONSHIP_CONFIDENCE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </Select>
              </Field>
              <Field label="Description">
                <Input value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
              </Field>
            </div>
            <div className="row-end" style={{ marginTop: 12 }}>
              <button type="submit" className="btn-primary" disabled={saving || !form.related_ci || !form.relationship_type}>
                {saving ? 'Saving…' : 'Add Relationship'}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>Outgoing Relationships</h2>
        {table(grouped.outgoing, 'outgoing')}
      </div>

      <div className="panel panel-pad">
        <h2 style={{ marginTop: 0 }}>Incoming Relationships</h2>
        {table(grouped.incoming, 'incoming')}
      </div>

      {confirm && (
        <ConfirmDialog
          open
          title="Remove relationship"
          message="This will remove the selected relationship. Continue?"
          confirmLabel="Remove"
          onCancel={() => setConfirm(null)}
          onConfirm={() => runAction(confirm.row, confirm.action)}
        />
      )}
    </div>
  );
}


