import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, Button } from '../../components';
import {
  listSources, getSource, enableSource, disableSource, rotateSourceSecret,
  testSource, parseMonitoringError,
} from '../../services/monitoring/monitoring-api';
import {
  AccessDeniedPanel, ErrorPanel, LoadingPanel, SourceStatusBadge,
  SourceHealthBadge,
} from '../../components/monitoring/MonitoringUI';
import { canAdministerMonitoring } from '../../components/monitoring/access';

/** Source Management — read-only listing plus supported actions.
 *
 * Backend-supported:
 *   GET    /monitoring/sources/          (list)
 *   GET    /monitoring/sources/<id>/     (retrieve)
 *   POST   /monitoring/sources/<id>/enable/
 *   POST   /monitoring/sources/<id>/disable/
 *   POST   /monitoring/sources/<id>/rotate-secret/
 *   POST   /monitoring/sources/<id>/test/
 *
 * Unsupported (no backend route): create (POST /monitoring/sources/),
 * edit (PATCH/PUT /monitoring/sources/<id>/).
 */
export function SourceManagement() {
  const auth = useAuth();
  const isAdmin = canAdministerMonitoring(auth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [detailId, setDetailId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(null);
  const [secretBusy, setSecretBusy] = useState(null);
  const [createdSecret, setCreatedSecret] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const s = await listSources();
      const arr = Array.isArray(s) ? s : (s?.results ?? []);
      setItems(arr);
    } catch (e) {
      setError(parseMonitoringError(e).global || 'Failed to load sources.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const viewDetail = (id) => { setDetailId(id); setDetailLoading(true); setDetail(null); };
  const closeDetail = () => { setDetailId(null); setDetail(null); };

  useEffect(() => {
    if (!detailId) return;
    (async () => {
      try { setDetail(await getSource(detailId)); }
      catch (e) { setError(parseMonitoringError(e).global || 'Failed to load source.'); }
      finally { setDetailLoading(false); }
    })();
  }, [detailId]);

  const toggleSource = async (id, enable) => {
    setActionBusy(id);
    try {
      if (enable) await enableSource(id); else await disableSource(id);
      setItems(items.map((i) => i.id === id ? { ...i, is_active: enable } : i));
    } catch (e) { setError(parseMonitoringError(e).global || 'Source action failed.'); }
    finally { setActionBusy(null); }
  };

  const rotateSecret = async (id) => {
    setSecretBusy(id);
    try {
      const r = await rotateSourceSecret(id);
      setCreatedSecret(r.secret ?? null);
    } catch (e) { setError(parseMonitoringError(e).global || 'Secret rotation failed.'); }
    finally { setSecretBusy(null); }
  };

  const testSourceConfig = async (id) => {
    try { await testSource(id); setError('Configuration valid.'); }
    catch (e) { setError(parseMonitoringError(e).global || 'Test failed.'); }
  };

  if (!isAdmin) {
    return (
      <div>
        <PageHeader title="Sources" sub="Monitoring source management." />
        <AccessDeniedPanel reason="access" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Sources"
        sub="Monitoring sources: read-only listing plus supported enable/disable, rotate-secret, and test actions."
        actions={<button type="button" className="btn-secondary" onClick={load}>Refresh</button>}
      />

      {error ? <ErrorPanel message={error} onRetry={load} /> : null}

      <div className="panel panel-pad">
        <div className="error-summary" role="alert">
          Source creation and editing are not available: the backend does not
          expose POST /monitoring/sources/ or PATCH/PUT /monitoring/sources/{'<id>'}/.{'\n'}
          Only list, retrieve, enable, disable, rotate-secret, and test are supported.
        </div>
      </div>

      {loading ? <LoadingPanel label="Loading sources…" /> : items.length === 0 ? (
        <div className="panel panel-pad">
          <div className="empty-state">
            <div className="empty-title">No monitoring sources configured.</div>
            <div className="small">Add a source requires backend create support.</div>
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Source</th><th>Code</th><th>Type</th><th>Status</th><th>Health</th><th>Active</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id}>
                  <td className="row-title">
                    {detailId === s.id ? (
                      <Button kind="ghost" size="small" onClick={() => viewDetail(s.id)}>{s.name}</Button>
                    ) : (
                      <a href="#" className="row-title" onClick={(e) => { e.preventDefault(); viewDetail(s.id); }}>{s.name}</a>
                    )}
                  </td>
                  <td className="cell-muted small">{s.code}</td>
                  <td className="cell-muted">{s.source_type}</td>
                  <td><SourceStatusBadge value={s.status} /></td>
                  <td><SourceHealthBadge value={s.health_status} /></td>
                  <td>{s.is_active ? <span className="badge badge-green">Yes</span> : <span className="badge badge-red">No</span>}</td>
                  <td className="cell-actions">
                    <Button kind="small" onClick={() => toggleSource(s.id, !s.is_active)} disabled={actionBusy === s.id}>
                      {s.is_active ? 'Disable' : 'Enable'}
                    </Button>
                    {isAdmin && (
                      <>
                        <Button kind="small" danger onClick={() => rotateSecret(s.id)} disabled={secretBusy === s.id} style={{ marginLeft: 4 }}>
                          Rotate secret
                        </Button>
                        <Button kind="small" onClick={() => testSourceConfig(s.id)} disabled={actionBusy === s.id} style={{ marginLeft: 4 }}>
                          Test
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head">
            <h3>{detail.name}</h3>
            <button type="button" className="btn-ghost btn-small" onClick={closeDetail}>Close</button>
          </div>
          <div className="panel-pad">
            {detailLoading ? <LoadingPanel label="Loading…" /> : (
              <>
                  <div className="small cell-muted">Read-only fields returned by the source serializer.</div>
                  <dl className="detail-grid">
                    <dt>Code</dt><dd>{detail.code}</dd>
                    <dt>Type</dt><dd>{detail.source_type}</dd>
                    <dt>Status</dt><dd><SourceStatusBadge value={detail.status} /></dd>
                    <dt>Health</dt><dd><SourceHealthBadge value={detail.health_status} /></dd>
                    <dt>Active</dt><dd>{detail.is_active ? 'Yes' : 'No'}</dd>
                  </dl>
                <div className="row-end" style={{ marginTop: 12 }}>
                  {detail.is_active ? (
                    <Button kind="small" danger onClick={() => toggleSource(detail.id, false)} disabled={actionBusy === detail.id}>Disable source</Button>
                  ) : (
                    <Button kind="small" onClick={() => toggleSource(detail.id, true)} disabled={actionBusy === detail.id}>Enable source</Button>
                  )}
                  {isAdmin && (
                    <>
                      <Button kind="small" onClick={() => testSourceConfig(detail.id)} disabled={actionBusy === detail.id} style={{ marginLeft: 4 }}>Test config</Button>
                      <Button kind="small" onClick={() => rotateSecret(detail.id)} disabled={secretBusy === detail.id} style={{ marginLeft: 4 }}>Rotate secret</Button>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {createdSecret && (
        <div className="success-summary" role="status">
          Secret rotated. The plaintext value is shown once — copy it now. It is not persisted.
          <div className="small" style={{ marginTop: 4 }}>
            <code style={{ wordBreak: 'break-all' }}>{createdSecret}</code>
          </div>
          <button type="button" className="btn-small btn-ghost" onClick={() => setCreatedSecret(null)} style={{ marginTop: 8 }}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}

export default SourceManagement;
