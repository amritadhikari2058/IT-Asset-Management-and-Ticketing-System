import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, Button } from '../../components';
import {
  AccessDeniedPanel, ErrorPanel, LoadingPanel, StatusBadge, SeverityBadge,
} from '../../components/monitoring/MonitoringUI';
import { getAlert, alertAction, parseMonitoringError } from '../../services/monitoring/monitoring-api';
import { canAdministerMonitoring } from '../../components/monitoring/access';

/** Alert Detail — safe summary from the supported retrieve endpoint only.
 *
 * Backend-supported:
 *   GET    /monitoring/alerts/<id>/          (retrieve)
 *   POST   /monitoring/alerts/<id>/acknowledge/
 *   POST   /monitoring/alerts/<id>/suppress/
 *   POST   /monitoring/alerts/<id>/unsuppress/
 *   POST   /monitoring/alerts/<id>/resolve/
 *   POST   /monitoring/alerts/<id>/close/
 *   POST   /monitoring/alerts/<id>/reopen/
 *   POST   /monitoring/alerts/<id>/assign/
 *
 * Serializer exposes only: alert_number, title, severity, status,
 * source_name, event_count.
 * Fields not exposed by the serializer are not rendered:
 *   environment, target, metric, fingerprint, first/last seen, recovery,
 *   occurrences detail, acknowledgements, linked ticket, automation state.
 * Events, history, and linked-ticket data are exposed through separate
 * backend viewsets. This page currently uses only the alert retrieve endpoint.
 */
export function AlertDetail({ alertId }) {
  const auth = useAuth();
  const canAdminister = canAdministerMonitoring(auth);
  const [alert, setAlert] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionBusy, setActionBusy] = useState('');

  useEffect(() => {
    if (!canAdminister || !alertId) return undefined;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const a = await getAlert(alertId);
        if (cancelled) return;
        setAlert(a);
      } catch (e) {
        const parsed = parseMonitoringError(e);
        if (!cancelled) setError(parsed.global || 'Failed to load alert.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [alertId, canAdminister]);

  const act = async (action, payload) => {
    setActionBusy(action);
    try {
      await alertAction(alertId, action, payload);
      setAlert(await getAlert(alertId));
    } catch (e) {
      const parsed = parseMonitoringError(e);
      setError(parsed.global || `Alert action failed.`);
    } finally {
      setActionBusy('');
    }
  };

  if (!canAdminister) {
    return (
      <div>
        <PageHeader title="Alert detail" sub="Correlated monitoring alert." />
        <AccessDeniedPanel reason="access" />
      </div>
    );
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Alert detail" sub="Correlated monitoring alert." />
        <LoadingPanel label="Loading alert…" />
      </div>
    );
  }

  if (error || !alert) {
    return (
      <div>
        <PageHeader title="Alert detail" sub="Correlated monitoring alert." />
        <ErrorPanel message={error || 'Alert not found.'} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  const ack = async () => {
    try { await act('acknowledge', {}); } catch { /* error surfaced in state */ }
  };
  const resolve = async () => {
    try { await act('resolve', {}); } catch { /* error surfaced in state */ }
  };
  const reopen = async () => {
    try { await act('reopen', {}); } catch { /* error surfaced in state */ }
  };

  return (
    <div>
      <PageHeader
        title={`Alert ${alert.alert_number ?? ''}`}
        sub={alert.title}
        actions={
          <div className="row-gap">
            <Button kind="secondary" onClick={() => window.history.back()}>Back</Button>
            {(alert.status === 'open' || alert.status === 'new') && (
              <Button kind="primary" disabled={actionBusy === 'acknowledge'} onClick={ack}>
                {actionBusy === 'acknowledge' ? 'Working…' : 'Acknowledge'}
              </Button>
            )}
            {(alert.status === 'open' || alert.status === 'acknowledged') && (
              <Button kind="primary" disabled={actionBusy === 'resolve'} onClick={resolve}>
                {actionBusy === 'resolve' ? 'Working…' : 'Resolve'}
              </Button>
            )}
            {alert.status !== 'open' && (
              <Button kind="primary" disabled={actionBusy === 'reopen'} onClick={reopen}>
                {actionBusy === 'reopen' ? 'Working…' : 'Reopen'}
              </Button>
            )}
          </div>
        }
      />

      {error ? <ErrorPanel message={error} /> : null}

      <div className="panel">
        <div className="panel-head"><h3>Alert summary</h3></div>
        <div className="panel-pad">
          <dl className="detail-grid">
            <dt>Alert</dt><dd>{alert.alert_number}</dd>
            <dt>Title</dt><dd>{alert.title}</dd>
            <dt>Severity</dt><dd><SeverityBadge value={alert.severity} /></dd>
            <dt>Status</dt><dd><StatusBadge value={alert.status} /></dd>
            <dt>Source</dt><dd>{alert.source_name ?? '—'}</dd>
            <dt>Event count</dt><dd>{alert.event_count ?? '—'}</dd>
          </dl>
        </div>
      </div>

      <div className="panel panel-pad">
        <div className="error-summary" role="status">
          Recovery details, occurrence history, correlation fingerprint,
          first/last seen, linked ticket, automation policy outcome, and retry
          state are not exposed by the alert retrieve serializer or by any
          supported backend endpoint, so they are not displayed here.
        </div>
      </div>
    </div>
  );
}

export default AlertDetail;
