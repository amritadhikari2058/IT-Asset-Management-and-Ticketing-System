import { useEffect, useState } from 'react';
import api from './api';
import { ConfirmDialog, EmptyState, PageHeader } from './components';

export function Notifications() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyAll, setBusyAll] = useState(false);
  const [allMsg, setAllMsg] = useState('');
  const [dismissTarget, setDismissTarget] = useState(null);
  const [dismissBusy, setDismissBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get('/common/notifications/');
      const list = r.data.results ?? r.data ?? [];
      setItems(Array.isArray(list) ? list : []);
      window.dispatchEvent(new Event('notif-change'));
    } catch {
      setError('Could not load notifications.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

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
      const r = await api.post('/common/notifications/mark_all_read/', {});
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
      await api.delete(`/common/notifications/${dismissTarget.id}/`);
      setItems((xs) => xs.filter((x) => x.id !== dismissTarget.id));
      setDismissTarget(null);
      window.dispatchEvent(new Event('notif-change'));
    } catch {
      setError(`Could not dismiss notification #${dismissTarget.id}.`);
    } finally {
      setDismissBusy(false);
    }
  };

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading notifications…
      </p>
    );
  }
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
                {n.entity_type === 'tickets.Ticket' && n.object_id ? (
                  <> · <a href={`#/tickets/${n.object_id}`}>Open ticket</a></>
                ) : null}
                {n.entity_type === 'assets.Asset' && n.object_id ? (
                  <> · <a href={`#/assets/${n.object_id}`}>Open asset</a></>
                ) : null}
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
        const r = await api.get('/common/notifications/');
        const list = r.data.results ?? r.data ?? [];
        if (!cancelled) setUnread(list.filter((n) => !n.is_read).length);
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
