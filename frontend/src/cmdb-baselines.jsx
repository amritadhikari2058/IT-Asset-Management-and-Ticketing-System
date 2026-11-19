import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { DataTable, EmptyState, Field, Input, LoadingRows, PageHeader, Select } from './components';
import { parseApiError } from './api-utils';
import {
  BASELINE_SCOPE_LABELS,
  BASELINE_STATUS_LABELS,
  formatDateTime,
  safeResults,
} from './cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS } from './cmdb';

function ciLabel(ci) {
  if (!ci) return '—';
  const num = ci.ci_number || `CI #${ci.id}`;
  return ci.name ? `${num} — ${ci.name}` : num;
}

function stringifyValue(v) {
  if (v == null || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function BaselinesPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [baselines, setBaselines] = useState([]);
  const [cis, setCis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [compareResult, setCompareResult] = useState(null);
  const [ciSearch, setCiSearch] = useState('');
  const [ciFilter, setCiFilter] = useState('');
  const [form, setForm] = useState({ name: '', description: '', scope_type: 'single_ci', configuration_items: [] });

  const canCreate = CMDB_PERMISSIONS.canCreateBaselines(role);
  const canApprove = CMDB_PERMISSIONS.canApproveBaselines(role);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [bRes, ciRes] = await Promise.all([
        api.get(CMDB_API_CONTRACT.baselinesList.endpoint),
        api.get('/cmdb/items/?page_size=500'),
      ]);
      const bRows = safeResults(bRes.data?.results ?? bRes.data);
      setBaselines(bRows);
      setCis(safeResults(ciRes.data?.results ?? ciRes.data));
      if (!selectedId && bRows.length) setSelectedId(bRows[0].id);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load baselines.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedBaseline = useMemo(() => baselines.find((b) => Number(b.id) === Number(selectedId)) || null, [baselines, selectedId]);
  const ciById = useMemo(() => {
    const map = new Map();
    cis.forEach((c) => map.set(Number(c.id), c));
    return map;
  }, [cis]);

  const filteredCis = useMemo(() => {
    const q = (ciSearch || '').trim().toLowerCase();
    return cis.filter((ci) => {
      if (ciFilter && Number(ci.id) !== Number(ciFilter)) return false;
      if (!q) return true;
      const hay = [ci.ci_number, ci.name, ci.status, ci.criticality, ci.environment].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [cis, ciSearch, ciFilter]);

  const selectedCiDetails = useMemo(() => (form.configuration_items || []).map((id) => ciById.get(Number(id))).filter(Boolean), [form.configuration_items, ciById]);

  const createBaseline = async (e) => {
    e.preventDefault();
    if (!canCreate || !form.name || !form.configuration_items.length) return;
    setSaving(true);
    setError('');
    setMsg('');
    try {
      const payload = {
        name: form.name,
        description: form.description || '',
        scope_type: form.scope_type,
        configuration_items: form.configuration_items.map(Number),
      };
      const res = await api.post(CMDB_API_CONTRACT.baselineCreate.endpoint, payload);
      setMsg(`Baseline ${res.data?.code || res.data?.id || ''} created.`);
      setForm({ name: '', description: '', scope_type: 'single_ci', configuration_items: [] });
      await load();
      if (res.data?.id) setSelectedId(res.data.id);
    } catch (err) {
      setError(parseApiError(err).global || 'Could not create baseline.');
    } finally {
      setSaving(false);
    }
  };

  const runAction = async (action) => {
    if (!selectedBaseline) return;
    setSaving(true);
    setError('');
    setMsg('');
    try {
      await api.post(`/cmdb/baselines/${selectedBaseline.id}/${action}/`, {});
      setMsg(`Baseline ${action} action completed.`);
      await load();
    } catch (err) {
      setError(parseApiError(err).global || `Could not ${action} baseline.`);
    } finally {
      setSaving(false);
    }
  };

  const compareBaseline = async () => {
    if (!selectedBaseline) return;
    setSaving(true);
    setError('');
    setMsg('');
    try {
      const res = await api.get(`/cmdb/baselines/${selectedBaseline.id}/compare/`);
      setCompareResult(res.data || null);
      if (res.data && (res.data.diffs || []).length === 0) setMsg('No differences found for this baseline.');
    } catch (err) {
      setCompareResult(null);
      setError(parseApiError(err).global || 'Could not compare baseline.');
    } finally {
      setSaving(false);
    }
  };

  const toggleCi = (ciId, checked) => {
    setForm((f) => {
      const set = new Set((f.configuration_items || []).map(Number));
      if (checked) set.add(Number(ciId)); else set.delete(Number(ciId));
      return { ...f, configuration_items: Array.from(set) };
    });
  };

  if (loading && !baselines.length) return <div className="panel panel-pad"><LoadingRows n={6} /></div>;

  const diffs = safeResults(compareResult?.diffs);
  const diffsByCi = diffs.reduce((acc, d) => {
    const key = d.ci_id ?? d.configuration_item ?? 'unknown';
    if (!acc[key]) acc[key] = [];
    acc[key].push(d);
    return acc;
  }, {});

  return (
    <div>
      <PageHeader title="Configuration Baselines" sub="Create, review, approve, compare, and supersede configuration baselines" />

      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-banner" role="status">{msg}</div>}

      <div className="split-grid split-2" style={{ marginBottom: 16 }}>
        <div className="panel panel-pad">
          <h2 style={{ marginTop: 0 }}>Baselines</h2>
          <DataTable
            columns={[
              { key: 'name', label: 'Baseline', render: (row) => <button type="button" className="link-button" onClick={() => { setSelectedId(row.id); setCompareResult(null); }}><strong>{row.name || row.code || `Baseline #${row.id}`}</strong><div className="muted">{row.code || '—'}</div></button> },
              { key: 'status', label: 'Status', render: (row) => BASELINE_STATUS_LABELS[row.status] || row.status || '—' },
              { key: 'scope_type', label: 'Scope', render: (row) => BASELINE_SCOPE_LABELS[row.scope_type] || row.scope_type || '—' },
              { key: 'ci_count', label: 'CIs', render: (row) => row.ci_count ?? (row.configuration_items || []).length ?? 0 },
              { key: 'created_at', label: 'Created', render: (row) => formatDateTime(row.created_at) },
            ]}
            rows={baselines}
            keyOf={(row) => row.id}
            emptyTitle="No baselines found."
            emptyHint="Create a baseline to capture expected configuration state."
          />
        </div>

        <div className="panel panel-pad">
          <h2 style={{ marginTop: 0 }}>Selected Baseline</h2>
          {!selectedBaseline ? (
            <EmptyState title="No baseline selected." hint="Select a baseline to review status and compare differences." />
          ) : (
            <div>
              <p><strong>{selectedBaseline.name}</strong> ({selectedBaseline.code || `#${selectedBaseline.id}`})</p>
              <p className="muted">Status: {BASELINE_STATUS_LABELS[selectedBaseline.status] || selectedBaseline.status} · Scope: {BASELINE_SCOPE_LABELS[selectedBaseline.scope_type] || selectedBaseline.scope_type} · CIs: {selectedBaseline.ci_count ?? (selectedBaseline.configuration_items || []).length}</p>
              <p className="muted">Approved: {formatDateTime(selectedBaseline.approved_at)} · Updated: {formatDateTime(selectedBaseline.updated_at || selectedBaseline.created_at)}</p>
              <div className="table-actions" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
                <button type="button" className="btn-small" onClick={compareBaseline} disabled={saving}>Compare (expected vs current)</button>
                {canCreate && selectedBaseline.status === 'draft' && <button type="button" className="btn-small" onClick={() => runAction('submit')} disabled={saving}>Submit for Approval</button>}
                {canApprove && selectedBaseline.status === 'pending_approval' && <button type="button" className="btn-small" onClick={() => runAction('approve')} disabled={saving}>Approve</button>}
                {canApprove && selectedBaseline.status === 'approved' && <button type="button" className="btn-small" onClick={() => runAction('supersede')} disabled={saving}>Supersede</button>}
              </div>
              <p className="muted">Lifecycle actions are enforced by backend permissions and status rules. Compare results show expected baseline values vs current CI values for drifted fields.</p>
              <h3>Scoped Configuration Items</h3>
              {(selectedBaseline.configuration_items || []).length === 0 ? <p className="muted">No CI scope data available.</p> : (
                <ul>
                  {(selectedBaseline.configuration_items || []).slice(0, 20).map((cid) => {
                    const ci = ciById.get(Number(cid));
                    return <li key={cid}><a href={`#/cmdb/items/${cid}`}>{ci ? ciLabel(ci) : `CI #${cid}`}</a> {ci ? <span className="muted">({ci.status}, {ci.criticality})</span> : null}</li>;
                  })}
                  {(selectedBaseline.configuration_items || []).length > 20 && <li className="muted">+ {(selectedBaseline.configuration_items || []).length - 20} more</li>}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {canCreate && (
        <div className="panel panel-pad" style={{ marginBottom: 16 }}>
          <h2 style={{ marginTop: 0 }}>Create Baseline</h2>
          <form onSubmit={createBaseline} noValidate>
            <div className="split-grid split-3">
              <Field label="Name" required>
                <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
              </Field>
              <Field label="Scope Type">
                <Select value={form.scope_type} onChange={(e) => setForm((f) => ({ ...f, scope_type: e.target.value }))}>
                  {Object.entries(BASELINE_SCOPE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </Select>
              </Field>
              <Field label="Description">
                <Input value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
              </Field>
            </div>
            <div className="split-grid split-2" style={{ marginTop: 12 }}>
              <Field label="Search CIs">
                <Input value={ciSearch} onChange={(e) => setCiSearch(e.target.value)} placeholder="Search by CI number, name, status…" />
              </Field>
              <Field label="Quick filter (exact CI)">
                <Select value={ciFilter} onChange={(e) => setCiFilter(e.target.value)}>
                  <option value="">All matching CIs</option>
                  {cis.slice(0, 300).map((ci) => <option key={ci.id} value={String(ci.id)}>{ciLabel(ci)}</option>)}
                </Select>
              </Field>
            </div>
            <div style={{ marginTop: 12 }}>
              <p className="muted">Select configuration items (searchable). Selected: {selectedCiDetails.length}. Summaries: {selectedCiDetails.slice(0, 5).map(ciLabel).join('; ')}{selectedCiDetails.length > 5 ? ` (+${selectedCiDetails.length - 5} more)` : ''}</p>
              <div style={{ maxHeight: 260, overflow: 'auto', border: '1px solid var(--border, #ddd)', borderRadius: 6, padding: 8 }}>
                {filteredCis.length === 0 ? <p className="muted">No configuration items match the current search.</p> : filteredCis.map((ci) => {
                  const checked = (form.configuration_items || []).map(Number).includes(Number(ci.id));
                  return (
                    <label key={ci.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
                      <input type="checkbox" checked={checked} onChange={(e) => toggleCi(ci.id, e.target.checked)} />
                      <span>{ciLabel(ci)} <span className="muted">— {ci.status} / {ci.criticality} / {ci.environment}</span></span>
                    </label>
                  );
                })}
              </div>
            </div>
            <div className="row-end" style={{ marginTop: 12 }}>
              <button type="submit" className="btn-primary" disabled={saving || !form.name || !form.configuration_items.length}>
                {saving ? 'Saving…' : 'Create Draft Baseline'}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="panel panel-pad">
        <h2 style={{ marginTop: 0 }}>Baseline Comparison (Expected vs Current)</h2>
        {!compareResult ? (
          <EmptyState title="No comparison run yet." hint="Select a baseline and click Compare to see expected versus current differences." />
        ) : diffs.length === 0 ? (
          <EmptyState title="No differences found." hint="Current CI state matches the selected baseline snapshot for compared fields." />
        ) : (
          <>
            <p className="muted">Baseline {compareResult.baseline_code || compareResult.baseline_id}: {diffs.length} difference{diffs.length === 1 ? '' : 's'} across {Object.keys(diffsByCi).length} CI(s).</p>
            <DataTable
              columns={[
                {
                  key: 'ci',
                  label: 'Affected CI',
                  render: (row) => {
                    const cid = row.ci_id ?? row.configuration_item;
                    const ci = ciById.get(Number(cid));
                    return cid ? <a href={`#/cmdb/items/${cid}`}>{row.ci_number || ci?.ci_number || `CI #${cid}`}{ci?.name ? ` — ${ci.name}` : ''}</a> : '—';
                  },
                },
                { key: 'field', label: 'Field', render: (row) => row.field_name || row.field || '—' },
                { key: 'expected', label: 'Expected (baseline)', render: (row) => stringifyValue(row.expected_value ?? row.expected) },
                { key: 'current', label: 'Current', render: (row) => stringifyValue(row.actual_value ?? row.current ?? row.current_value) },
                { key: 'type', label: 'Difference', render: (row) => row.change_type || row.diff_type || (row.expected_value !== row.actual_value ? 'changed' : '—') },
                {
                  key: 'actions',
                  label: 'Navigate',
                  render: (row) => {
                    const cid = row.ci_id ?? row.configuration_item;
                    return cid ? (
                      <div className="table-actions">
                        <a className="btn-small" href={`#/cmdb/items/${cid}`}>Open CI</a>
                        <a className="btn-small" href={`#/cmdb/items/${cid}/dependencies`}>Dependencies</a>
                      </div>
                    ) : '—';
                  },
                },
              ]}
              rows={diffs}
              keyOf={(row, i) => `${row.ci_id || row.configuration_item}-${row.field_name || i}-${i}`}
              emptyTitle="No differences."
              emptyHint="No drift detected."
            />
          </>
        )}
      </div>
    </div>
  );
}
