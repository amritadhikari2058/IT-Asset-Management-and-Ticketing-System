/** Linked Ticket display — read-only, backend-unsupported.
 *
 * The alert ticket sub-action (GET /monitoring/alerts/<id>/ticket/) is
 * registered in urls.py but has no corresponding method on
 * MonitoringAlertViewSet, so it is not called. This panel renders a clear
 * unavailable state and links to the existing Ticket route only when a ticket
 * identifier is already known from outside Monitoring.
 */
export function LinkedTicketPanel({ ticketId }) {
  return (
    <div className="panel">
      <div className="panel-head"><h3>Linked ticket</h3></div>
      <div className="panel-pad">
        <div className="error-summary" role="status">
          Linked ticket lookup is not available: the alert ticket endpoint
          (GET /monitoring/alerts/{'<id>'}/ticket/) is not implemented on the
          backend. Ticket details cannot be surfaced from Monitoring.
        </div>
        {ticketId ? (
          <div className="small" style={{ marginTop: 8 }}>
            If a ticket identifier is known externally, open it directly:
            <a href={`#/tickets/${ticketId}`} style={{ marginLeft: 8 }}>Ticket #{ticketId}</a>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default LinkedTicketPanel;
