export const fmtDate = (d) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString() : '—');
export const fmtDateTime = (d) => (d ? new Date(d).toLocaleString() : '—');
