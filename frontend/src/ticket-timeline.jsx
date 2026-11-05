export function TicketTimeline({ id }) {
  return (
    <div className="panel">
      <h2>Ticket timeline</h2>
      <p className="muted">{id ? `Timeline for ticket #${id} is not available in this build.` : 'Select a ticket to view its timeline.'}</p>
    </div>
  );
}
