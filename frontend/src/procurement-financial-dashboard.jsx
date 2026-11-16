import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { formatMoney, statusLabel, procurementErrorText } from './procurement-utils';

function Table({ columns, rows, empty = 'No records.' }) {
  if (!rows?.length) return <div className="empty-state"><div className="empty-title">{empty}</div></div>;
  return <div className="table-wrap"><table className="table"><thead><tr>{columns.map(c => <th key={c.key || c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.id ?? i}>{columns.map(c => <td key={c.key || c.label}>{typeof c.render === 'function' ? c.render(row) : row[c.key]}</td>)}</tr>)}</tbody></table></div>;
}

function moneyOrDash(value) {
  return value === null || value === undefined ? '—' : formatMoney(value);
}

export function ProcurementFinancialDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setError('');
    return api.get('/procurement/financial-dashboard/')
      .then(r => setData(r.data))
      .catch(e => setError(procurementErrorText(e, 'Failed to load financial dashboard.')))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="page-loading" role="status">Loading financial dashboard…</p>;
  if (error) return <div role="alert" className="error">{error} <button className="btn" onClick={load}>Retry</button></div>;
  const c = data?.cards || {};
  const cards = [
    ['Draft', c.draft], ['Submitted', c.submitted], ['Awaiting Match', c.awaiting_match], ['Matched', c.matched],
    ['Match Exceptions', c.match_exceptions], ['Approval Pending', c.approval_pending],
    ['Payment Holds', c.payment_holds], ['Payment Ready', c.payment_ready], ['Paid in Period', c.paid_in_period],
    ['Overdue', c.overdue], ['Open Returns', c.open_returns], ['Pending Credits', c.pending_credits],
    ['High/Critical Exceptions', c.unresolved_high_critical],
    ['Match Rate', c.match_rate === null || c.match_rate === undefined ? '—' : `${c.match_rate}%`],
    ['Exception Rate', c.exception_rate === null || c.exception_rate === undefined ? '—' : `${c.exception_rate}%`],
  ];
  const totals = data?.totals_by_currency || [];
  return (
    <div>
      <h1>Procurement Financial Dashboard</h1>
      <div className="card-grid" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))',gap:'12px'}}>
        {cards.map(([label, value]) => <div key={label} className="card"><div className="small">{label}</div><div style={{fontSize:'1.4rem',fontWeight:700}}>{value ?? 0}</div></div>)}
      </div>
      <h2>Financial Totals by Currency</h2>
      <Table columns={[
        { label: 'Currency', key: 'currency' }, { label: 'Invoiced', render: r => moneyOrDash(r.invoiced) },
        { label: 'Approved', render: r => moneyOrDash(r.approved) },
        { label: 'Payment Ready', render: r => moneyOrDash(r.payment_ready) }, { label: 'Paid', render: r => moneyOrDash(r.paid) },
        { label: 'Credit Note Total', render: r => moneyOrDash(r.credit_note_total) },
        { label: 'Exception Value', render: r => moneyOrDash(r.exception_value) }, { label: 'Outstanding', render: r => moneyOrDash(r.outstanding) },
      ]} rows={totals} empty="No financial totals." />
      <p className="small">Currencies are never combined.</p>
      <h2>Recent Invoices</h2>
      <Table columns={[{ label: 'Invoice', render: r => <a href={`#/procurement/invoices/${r.id}`}>{r.invoice_number}</a> }, { label: 'Vendor', render: r => r.vendor_name }, { label: 'Status', render: r => statusLabel(r.status) }, { label: 'Total', render: r => formatMoney(r.grand_total, r.currency) }]} rows={data?.recent_invoices || []} />
      <h2>Critical Exceptions</h2>
      <Table columns={[{ label: 'Invoice', render: r => r.invoice_number || r.invoice }, { label: 'Type', key: 'exception_type' }, { label: 'Severity', key: 'severity' }, { label: 'Status', render: r => statusLabel(r.status) }]} rows={data?.critical_exceptions || []} />
      <h2>Payment-Ready Invoices</h2>
      <Table columns={[{ label: 'Invoice', render: r => r.invoice_number }, { label: 'Vendor', render: r => r.vendor_name }, { label: 'Total', render: r => formatMoney(r.grand_total, r.currency) }]} rows={data?.payment_ready_invoices || []} />
      <h2>Overdue Invoices</h2>
      <Table columns={[{ label: 'Invoice', render: r => r.invoice_number }, { label: 'Vendor', render: r => r.vendor_name }, { label: 'Due Date', key: 'due_date' }, { label: 'Total', render: r => formatMoney(r.grand_total, r.currency) }]} rows={data?.overdue_invoices || []} />
      <h2>Open Vendor Returns</h2>
      <Table columns={[{ label: 'Return', render: r => r.return_number }, { label: 'Vendor', render: r => r.vendor_name }, { label: 'Status', render: r => statusLabel(r.status) }]} rows={data?.open_vendor_returns || []} />
      <h2>Credits Awaiting Application</h2>
      <Table columns={[{ label: 'Credit Note', render: r => r.credit_note_number }, { label: 'Vendor', render: r => r.vendor_name }, { label: 'Status', render: r => statusLabel(r.status) }, { label: 'Total', render: r => formatMoney(r.total, r.currency) }]} rows={data?.credits_awaiting_application || []} />
    </div>
  );
}

export default ProcurementFinancialDashboard;
