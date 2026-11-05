export function TicketCollaborationPanel({ id }) {
  return (
    <div className="panel">
      <h2>Ticket collaboration</h2>
      <p className="muted">{id ? `Collaboration for ticket #${id} is not available in this build.` : 'Collaboration tools are not available in this build.'}</p>
    </div>
  );
}
