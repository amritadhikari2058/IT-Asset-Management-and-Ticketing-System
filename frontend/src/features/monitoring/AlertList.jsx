import { useAuth } from '../../auth';
import { PageHeader } from '../../components';
import { AccessDeniedPanel } from '../../components/monitoring/MonitoringUI';
import { canAccessMonitoring } from '../../components/monitoring/access';

/** Alert List — backend has no Alert collection endpoint
 *  (GET /monitoring/alerts/ is not registered; only retrieve by id).
 *
 *  The page does not issue a request to any unsupported URL. It renders a
 *  clear unavailable state and links to the supported Alert detail workflow
 *  only when an alert identifier is already known from elsewhere.
 */
export function AlertList() {
  const auth = useAuth();

  if (!canAccessMonitoring(auth)) {
    return (
      <div>
        <PageHeader title="Alerts" sub="Correlated operational alerts." />
        <AccessDeniedPanel reason="access" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Alerts"
        sub="Alert list API unavailable on the backend."
      />
      <div className="panel panel-pad" role="status" aria-label="Alert list unavailable">
        <div className="error-summary" role="alert">
          The Alert collection endpoint (GET /monitoring/alerts/) is not
          registered on the backend, so the alert list cannot be loaded.
          Individual alert details can still be viewed when an alert
          identifier is already known.
        </div>
        <div className="small cell-muted">
          Supported: alert retrieve and actions (acknowledge, suppress,
          resolve, reopen, etc.) by alert id.
        </div>
      </div>
    </div>
  );
}

export default AlertList;
