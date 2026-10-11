import { useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { THEME } from './theme';

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('admin@local');
  const [password, setPassword] = useState('admin12345');
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try { await login(email, password); location.hash = '#/tickets'; }
    catch { setErr('Login failed. Is the backend running + seeded?'); }
  };
  return (
    <div style={{ maxWidth: 360, margin: '8% auto', background: THEME.mainBackground,
      border: `1px solid ${THEME.borders}`, borderRadius: 8, padding: 24 }}>
      <h2 style={{ color: THEME.primaryDarkRed }}>Ticket &amp; Asset System</h2>
      <form onSubmit={submit}>
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email"
          style={{ width: '100%', marginBottom: 8, padding: 8 }} />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder="password" style={{ width: '100%', marginBottom: 8, padding: 8 }} />
        {err && <p style={{ color: THEME.primaryDarkRed }}>{err}</p>}
        <button type="submit" style={{ background: THEME.primaryDarkRed, color: '#fff',
          padding: '8px 16px', border: 0, borderRadius: 4, width: '100%' }}>Log in</button>
      </form>
      <p style={{ fontSize: 12, color: THEME.mainText }}>Seeded: admin@local / manager@local / support@local / employee@local</p>
    </div>
  );
}

function Table({ cols, rows }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
      <thead><tr>{cols.map((c) => (
        <th key={c} style={{ textAlign: 'left', borderBottom: `1px solid ${THEME.borders}`, padding: 6 }}>{c}</th>))}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i} style={{ background: i % 2 ? THEME.supportingBackground : THEME.mainBackground }}>
          {cols.map((c) => <td key={c} style={{ padding: 6 }}>{String(r[c] ?? '')}</td>)}
        </tr>))}</tbody>
    </table>
  );
}

export function Tickets() {
  const { canCreateTickets } = useAuth();
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(new Set());
  const [report, setReport] = useState(null);
  const load = async () => {
    const r = await api.get('/tickets/');
    setItems(r.data.results ?? r.data);
  };
  const loadReport = async () => {
    const r = await api.get('/tickets/reports/by-category/');
    setReport(r.data.results);
  };
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const bulk = async (changes) => {
    const ids = [...sel];
    const prev = await api.post('/tickets/bulk_update/', { ids, changes, preview: true });
    if (!confirm(`Affects ${prev.data.affected}. Invalid: ${prev.data.invalid_transitions.length}. Confirm?`)) return;
    const res = await api.post('/tickets/bulk_update/', { ids, changes, preview: false, confirm: true });
    alert(`OK ${res.data.summary.ok}, skipped ${res.data.summary.skipped}, failed ${res.data.summary.failed}`);
    load();
  };
  return (
    <div>
      <h3>Tickets</h3>
      <button onClick={load} style={{ background: THEME.secondaryIndigo, color: '#fff', border: 0, borderRadius: 4, padding: '6px 12px' }}>Load</button>{' '}
      {canCreateTickets && <a href="#/tickets/new" style={{ background: THEME.primaryDarkRed, color: '#fff', border: 0, borderRadius: 4, padding: '6px 12px', textDecoration: 'none' }}>+ New ticket</a>}{' '}
      <button onClick={loadReport} style={{ border: `1px solid ${THEME.borders}`, borderRadius: 4, padding: '6px 12px' }}>Category report</button>
      <div style={{ marginTop: 8 }}>
        <button onClick={() => bulk({ status: 'closed' })}>Bulk close</button>{' '}
        <button onClick={() => bulk({ priority: 'high' })}>Bulk priority=high</button>
      </div>
      <Table cols={['id', 'title', 'status', 'priority']} rows={items.map((t) => ({ ...t }))} />
      <div>{items.map((t) => (
        <span key={t.id} style={{ marginRight: 12 }}>
          <label style={{ marginRight: 4 }}>
            <input type="checkbox" checked={sel.has(t.id)} onChange={() => toggle(t.id)} /> #{t.id}
          </label>
          <a href={`#/tickets/${t.id}`}>Open</a>
        </span>))}</div>
      {report && (
        <div style={{ marginTop: 16 }}>
          <h4>Tickets by category (DB aggregation)</h4>
          {report.map((r) => (
            <div key={r.id} style={{ marginBottom: 6 }}>
              <b>{r.name}</b> total {r.total} · open {r.open_count} · closed {r.closed_count} · high {r.high_count ?? 0} · critical {r.critical_count ?? 0} · urgent {r.urgent}
              <div style={{ background: THEME.supportingBackground, borderRadius: 4 }}>
                <div style={{ width: `${r.total ? (r.open_count / r.total) * 100 : 0}%`,
                  background: THEME.secondaryIndigo, height: 8, borderRadius: 4 }} />
              </div>
            </div>))}
        </div>)}
    </div>
  );
}

export function Assets() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(new Set());
  const load = async () => {
    const r = await api.get('/assets/');
    setItems(r.data.results ?? r.data);
  };
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const retire = async () => {
    for (const id of sel) await api.post(`/assets/${id}/retire/`);
    alert('Retired selected (history kept).'); load();
  };
  return (
    <div>
      <h3>Assets</h3>
      <button onClick={load} style={{ background: THEME.secondaryIndigo, color: '#fff', border: 0, borderRadius: 4, padding: '6px 12px' }}>Load</button>{' '}
      {isStaff && <a href="#/assets/new" style={{ background: THEME.primaryDarkRed, color: '#fff', border: 0, borderRadius: 4, padding: '6px 12px', textDecoration: 'none' }}>+ New asset</a>}{' '}
      <button onClick={retire}>Retire selected (safe, keeps history)</button>
      <Table cols={['id', 'asset_tag', 'name', 'status']} rows={items} />
      <div>{items.map((a) => (
        <span key={a.id} style={{ marginRight: 12 }}>
          <label style={{ marginRight: 4 }}>
            <input type="checkbox" checked={sel.has(a.id)} onChange={() => toggle(a.id)} /> {a.asset_tag}
          </label>
          <a href={`#/assets/${a.id}`}>Open</a>
        </span>))}</div>
      <p style={{ fontSize: 12 }}>Assignment changes use the explicit assign endpoint — bulk update rejects assignment keys (tested).</p>
    </div>
  );
}

export function Categories() {
  const [acats, setAcats] = useState([]);
  const [tcats, setTcats] = useState([]);
  const [name, setName] = useState('');
  const [which, setWhich] = useState('ticket');
  const load = async () => {
    setAcats((await api.get('/assets/categories/')).data.results ?? []);
    setTcats((await api.get('/tickets/categories/')).data.results ?? []);
  };
  const add = async () => {
    const url = which === 'ticket' ? '/tickets/categories/' : '/assets/categories/';
    try { await api.post(url, { name }); setName(''); load(); }
    catch (e) { alert(e.response?.status === 403 ? 'Forbidden: employees cannot add categories.' : 'Failed'); }
  };
  return (
    <div>
      <h3>Managed categories (dropdown sources)</h3>
      <button onClick={load}>Load</button>
      <div style={{ margin: '8px 0' }}>
        <select value={which} onChange={(e) => setWhich(e.target.value)}>
          <option value="ticket">Ticket category</option>
          <option value="asset">Asset category</option>
        </select>{' '}
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New category name" />{' '}
        <button onClick={add} style={{ background: THEME.primaryDarkRed, color: '#fff', border: 0, borderRadius: 4, padding: '6px 12px' }}>+ Add</button>
      </div>
      <h4>Ticket categories</h4>
      <Table cols={['id', 'name', 'is_active']} rows={tcats} />
      <h4>Asset categories</h4>
      <Table cols={['id', 'name', 'is_active']} rows={acats} />
    </div>
  );
}

export function RecycleBin() {
  const [items, setItems] = useState([]);
  const load = async () => {
    try { setItems((await api.get('/recycle-bin/')).data); }
    catch { alert('System Admin only.'); }
  };
  const restore = async (e) => {
    const r = await api.post(`/recycle-bin/${e.entity_type}/${e.object_id}/restore/`, {}).catch((x) => x.response);
    alert(r.status === 200 ? 'Restored' : `Blocked: ${JSON.stringify(r.data.blockers ?? r.data)}`);
    load();
  };
  const hardDelete = async (e) => {
    const id = prompt(`PERMANENT delete ${e.entity_type}:${e.object_id}. Re-type the ID to confirm:`);
    if (id !== e.object_id) return;
    const reason = prompt('Reason (required, audited):');
    if (!reason) return;
    const r = await api.post(`/recycle-bin/${e.entity_type}/${e.object_id}/permanent/`,
      { confirm: id, reason }).catch((x) => x.response);
    alert(r.status === 200 ? 'Permanently deleted (audited).' : JSON.stringify(r.data));
    load();
  };
  return (
    <div>
      <h3 style={{ color: THEME.primaryDarkRed }}>Recycle Bin (System Admin only)</h3>
      <button onClick={load}>Load deleted records</button>
      <Table cols={['entity_type', 'object_id', 'repr', 'deleted_by', 'deletion_reason']} rows={items} />
      {items.map((e, i) => (
        <div key={i} style={{ marginTop: 4 }}>
          <button onClick={() => restore(e)}>Restore</button>{' '}
          <button onClick={() => hardDelete(e)} style={{ background: THEME.primaryDarkRed, color: '#fff', border: 0, borderRadius: 4, padding: '4px 10px' }}>
            Permanent delete…
          </button>
        </div>))}
    </div>
  );
}

export function VerifyEmail() {
  const [msg, setMsg] = useState('Verifying…');
  const run = async () => {
    const q = new URLSearchParams(location.hash.split('?')[1] || '');
    try {
      const r = await api.get(
        `/accounts/verify-email/confirm/?uid=${q.get('uid')}&token=${q.get('token')}`);
      setMsg(r.data.detail);
    } catch { setMsg('Invalid or expired link.'); }
  };
  useState(() => { run(); });
  return <div><h3>Email verification</h3><p>{msg}</p><a href="#/tickets">Back</a></div>;
}

export function ResetPassword() {
  const [pwd, setPwd] = useState('');
  const [msg, setMsg] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    const q = new URLSearchParams(location.hash.split('?')[1] || '');
    try {
      const r = await api.post('/accounts/password-reset/confirm/',
        { uid: q.get('uid'), token: q.get('token'), new_password: pwd });
      setMsg(r.data.detail);
    } catch { setMsg('Invalid or expired link (min 8 chars).'); }
  };
  return (
    <div style={{ maxWidth: 360 }}>
      <h3>Set new password</h3>
      <form onSubmit={submit}>
        <input type="password" value={pwd} onChange={(e) => setPwd(e.target.value)}
          placeholder="new password (8+)" style={{ width: '100%', padding: 8, marginBottom: 8 }} />
        <button type="submit">Update</button>
      </form>
      <p>{msg}</p>
    </div>
  );
}

export function Profile() {
  const { user, refreshProfile } = useAuth();
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  if (!user) return <p>Loading profile…</p>;
  const enabled = user.receive_ticket_emails !== false;
  const toggle = async () => {
    if (saving) return;
    setSaving(true);
    setMsg('');
    setErr('');
    try {
      await api.patch('/accounts/me/', { receive_ticket_emails: !enabled });
      await refreshProfile();
      setMsg(enabled ? 'Ticket-event emails turned off.' : 'Ticket-event emails turned on.');
    } catch {
      setErr('Could not save preference.');
    } finally {
      setSaving(false);
    }
  };
  return (
    <div style={{ maxWidth: 560 }}>
      <h3>My profile</h3>
      <dl className="detail-grid">
        <dt>Employee ID</dt><dd>{user.employee_id}</dd>
        <dt>Email</dt><dd>{user.email}</dd>
        <dt>Role</dt><dd>{user.role}</dd>
      </dl>
      <h4>Email preferences</h4>
      <label className="check-row">
        <input type="checkbox" checked={enabled} onChange={toggle} disabled={saving} />
        Receive ticket-event emails
      </label>
      <p className="muted small" style={{ marginTop: 6 }}>
        Applies to assignment and status-change emails only. In-app notifications,
        password resets, and email verification are always sent.
      </p>
      {saving && <p className="muted">Saving…</p>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      {err && <div className="error-summary" role="alert">{err}</div>}
    </div>
  );
}

export function Users() {  const [msg, setMsg] = useState('');
  const run = async (kind) => {
    const ids = prompt('Comma-separated user IDs:');
    if (!ids) return;
    const list = ids.split(',').map((s) => Number(s.trim())).filter(Boolean);
    const url = kind === 'activate' ? '/accounts/users/bulk_activate/' : '/accounts/users/bulk_delete/';
    const prev = await api.post(url, { ids: list, preview: true, ...(kind === 'activate' ? { activate: true } : {}) });
    if (!confirm(`Affects ${prev.data.affected ?? prev.data.preview?.length}. Confirm?`)) return;
    const res = await api.post(url, { ids: list, preview: false, confirm: true, ...(kind === 'activate' ? { activate: true } : { reason: 'bulk' }) });
    setMsg(JSON.stringify(res.data));
  };
  return (
    <div>
      <h3>Employees (bulk)</h3>
      <button onClick={() => run('activate')}>Bulk activate (preview → confirm)</button>{' '}
      <button onClick={() => run('delete')}>Bulk soft-delete (history rows skip)</button>
      <pre>{msg}</pre>
      <p style={{ fontSize: 12 }}>Import template: GET /api/accounts/users/bulk_import/ · key: employee_id · roles never change via bulk.</p>
    </div>
  );
}
