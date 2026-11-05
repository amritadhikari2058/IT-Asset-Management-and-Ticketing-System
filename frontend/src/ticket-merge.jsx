export function TicketMergeDialog({ id }) {
  return (
    <div className="panel">
      <h2>Merge ticket</h2>
      <p className="muted">{id ? `Merge workflow for ticket #${id} is not available in this build.` : 'Select a ticket to merge.'}</p>
    </div>
  );
}
