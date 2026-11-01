import { useEffect, useState } from 'react';
import api from './api';
import { ConfirmDialog, EmptyState, PageHeader } from './components';
import { Pager } from './components';

export function Notifications() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyAll, setBusyAll] = useState(false);
  const [allMsg, setAllMsg] = useState('');
  const [dismissTarget, setDismissTarget] = useState(null);
  const [dismissBusy, setDismissBusy] = useState(false);

  const [filter, setFilter] = useState('all'); // 'all'|'unread'
  const [entity, setEntity] = useState(''); // ''|'tickets.Ticket'|'assets.Asset'|'assets.Maintenance'|'assets.Disposal'

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const p = new URLSearchParams();
      if (filter !== 'all') p.set('is_read', filter === 'unread' ? 'false' : 'true');
      if (entity) p.set('entity_type', entity);
      const r = await api.get(`/api/common/notifications/?${p.toString()}`);
      const list = r.data.results ?? r.data ?? [];
      setItems(Array.isArray(list) ? list : []);
      window.dispatchEvent(new Event('notif-change'));
    } catch {
      setError('Could not load notifications.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [filter, entity]);

  const unread = items.filter((n) => !n.is_read).length;

  const markOneRead = async (n) => {
    try {
      const r = await api.patch(`/common/notifications/${n.id}/`, { is_read: true });
      setItems((xs) => xs.map((x) => (x.id === n.id ? r.data : x)));
      window.dispatchEvent(new Event('notif-change'));
    } catch {
      setError(`Could not mark notification #${n.id} as read.`);
    }
  };

  const markAllRead = async () => {
    if (busyAll || unread === 0) return;
    setBusyAll(true);
    setAllMsg('');
    setError('');
    try {
      const r = await api.post('/api/common/notifications/mark_all_read/', {});
      setAllMsg(`Marked ${r.data.updated ?? 0} notification(s) as read.`);
      await load();
    } catch {
      setError('Could not mark all as read.');
    } finally {
      setBusyAll(false);
    }
  };

  const dismiss = async () => {
    if (!dismissTarget || dismissBusy) return;
    setDismissBusy(true);
    try {
      await api.delete(`/api/common/notifications/${dismissTarget.id}/`);
      setItems((xs) => xs.filter((x) => x.id !== dismissTarget.id));
      setDismissTarget(null);
      window.dispatchEvent(new Event('notif-change'));
    } catch {
      setError(`Could not dismiss notification #${dismissTarget.id}.`);
    } finally {
      setDismissBusy(false);
    }
  };

  const entityLinks = {
    'tickets.Ticket': (id) => ({ href: `#/tickets/${id}`, label: 'Open ticket' }),
    'assets.Asset': (id) => ({ href: `#/assets/${id}`, label: 'Open asset' }),
    'assets.Maintenance': () => ({ href: '#/maintenance', label: 'Open maintenance' }),
    'assets.Disposal': () => ({ href: '#/disposals', label: 'Open disposals' }),
  };

  return (
    <div>
      <PageHeader
        title="Notifications"
        sub={unread > 0 ? `${unread} unread` : 'All caught up.'}
        actions={<>
          <button type="button" className="btn-ghost" onClick={load}>Refresh</button>
          <button
            type="button" className="btn-secondary"
            onClick={markAllRead} disabled={busyAll || unread === 0}
            title={unread === 0 ? 'Nothing unread' : 'Mark all as read'}
          >
            {busyAll ? 'Working…' : 'Mark all as read'}
          </button>
        </>}
      />
      <div className="filter-bar" role="search">
        <select
          className="input"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter by read status"
        >
          <option value="all">All</option>
          <option value="unread">Unread only</option>
          <option value="read">Read only</option>
        </select>
        <select
          className="input"
          value={entity}
          onChange={(e) => setEntity(e.target.value)}
          aria-label="Filter by entity type"
        >
          <option value="">All types</option>
          <option value="tickets.Ticket">Tickets</option>
          <option value="assets.Asset">Assets</option>
          <option value="assets.Maintenance">Maintenance</option>
          <option value="assets.Disposal">Disposals</option>
        </select>
      </div>
      {error && <div className="error-summary" role="alert">{error}</div>}
      {allMsg && <div className="success-summary" role="status">{allMsg}</div>}
      {items.length === 0 ? (
        <EmptyState title="No notifications." hint="Ticket and asset events that involve you will show up here." />
      ) : (
        <ul className="note-list">
          {items.map((n) => (
            <li key={n.id} className={n.is_read ? undefined : 'is-unread'}>
              <div className={n.is_read ? 'notif-title' : 'notif-title is-strong'}>{n.title}</div>
              {n.body && <div className="pre-wrap">{n.body}</div>}
              <div className="muted small">
                {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                {n.entity_type ? ` · ${n.entity_type}:${n.object_id}` : ''}
                {entityLinks[n.entity_type] && n.object_id
  ? <a href={entityLinks[n.entity_type](n.object_id).href}>
      {entityLinks[n.entity_type](n.object_id).label}
    </a>
  : null}
              </div>
              <div className="notif-actions">
                {!n.is_read && (
                  <button type="button" className="btn-ghost" onClick={() => markOneRead(n)}>
                    Mark as read
                  </button>
                )}
                <button type="button" className="btn-ghost" onClick={() => setDismissTarget(n)}>
                  Dismiss…
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {dismissTarget && (
        <ConfirmDialog
          title="Dismiss notification?"
          message={`"${dismissTarget.title}" will be removed from your list. This cannot be undone from here.`}
          confirmLabel="Dismiss"
          busy={dismissBusy}
          onConfirm={dismiss}
          onCancel={() => setDismissTarget(null)}
        />
      )}
    </div>
  );
}

export function NotifBadge() {
  const [unread, setUnread] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const fetchCount = async () => {
      try {
        const r = await api.get('/api/common/notifications/unread_count/');
        const data = r.data || r;
        if (!cancelled) setUnread(data.count ?? data ?? 0);
      } catch {
        if (!cancelled) setUnread(null);
      }
    };
    fetchCount();
    const onHash = () => fetchCount();
    const onChange = () => fetchCount();
    addEventListener('hashchange', onHash);
    addEventListener('notif-change', onChange);
    return () => {
      cancelled = true;
      removeEventListener('hashchange', onHash);
      removeEventListener('notif-change', onChange);
    };
  }, []);
  if (!unread) return null;
  return <span className="count-badge">{unread}</span>;
}
