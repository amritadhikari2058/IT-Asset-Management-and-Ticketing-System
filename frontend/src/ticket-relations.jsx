export function TicketRelationsPanel({ id }) {
  return (
    <div className="panel">
      <h2>Ticket relations</h2>
      <p className="muted">{id ? `Relations for ticket #${id} are not available in this build.` : 'Select a ticket to manage relations.'}</p>
    </div>
  );
}
