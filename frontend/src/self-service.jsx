import { useEffect, useState } from 'react';
import api from './api';
import { PageHeader, EmptyState, Panel, PanelHeader, PanelPad, Link } from './components';
import { NotifBadge } from './notifications';
import { useAuth } from './auth';

const PAGE_SIZE = 20;

export function SelfService() {
  const { user } = useAuth();

  // ---- Ticket list (own tickets) ----
  const [tickets, setTickets] = useState([]);
  const [ticketLoading, setTicketLoading] = useState(true);
  const [ticketError, setTicketError] = useState('');

  const loadTickets = async () => {
    setTicketLoading(true);
    setTicketError('');
    try {
      const r = await api.get('/tickets/');
      setTickets(r.data.results ?? r.data ?? []);
    } catch (e) {
      setTicketError('Could not load your tickets.');
    } finally {
      setTicketLoading(false);
    }
  };

  // ---- Assigned assets ----
  const [assets, setAssets] = useState([]);
  const [assetLoading, setAssetLoading] = useState(true);
  const [assetError, setAssetError] = useState('');

  const loadAssets = async () => {
    setAssetLoading(true);
    setAssetError('');
    try {
      const r = await api.get('/assets/');
      const myAssets = (r.data.results ?? r.data ?? []).filter(
        (a) => a.assigned_to_id === user.id || a.created_by_id === user.id
      );
      setAssets(myAssets);
    } catch (e) {
      setAssetError('Could not load your assets.');
    } finally {
      setAssetLoading(false);
    }
  };

  // ---- Knowledge‑base search ----
  const [kbQuery, setKbQuery] = useState('');
  const [kbResults, setKbResults] = useState([]);
  const [kbLoading, setKbLoading] = useState(false);
  const [kbError, setKbError] = useState('');

  const loadKb = async () => {
    if (!kbQuery.trim()) {
      setKbResults([]);
      return;
    }
    setKbLoading(true);
    setKbError('');
    try {
      const r = await api.get('/common/knowledge-base/', {
        params: { q: kbQuery },
      });
      setKbResults(r.data.results ?? r.data ?? []);
    } catch (e) {
      setKbError('Could not search knowledge base.');
    } finally {
      setKbLoading(false);
    }
  };

  useEffect(() => {
    loadTickets();
    loadAssets();
  }, []);

  // ---- Helper: render tickets section ----
  function renderTickets() {
    if (ticketLoading) {
      return <EmptyState title="Loading tickets..." hint="Please wait…" />;
    }
    if (ticketError) {
      return <EmptyState title="Error" hint={ticketError} />;
    }
    if (tickets.length === 0) {
      return <EmptyState
        title="No tickets"
        hint="You have no tickets. Create a new ticket if you need help."
      />;
    }
    return (
      <ul className="note-list">
        {tickets.map((t) => (
          <li key={t.id} className={t.is_read ? undefined : 'is-unread'}>
            <div className="muted small">
              {t.priority ? t.priority[0].toUpperCase() + t.priority.slice(1) : '—'}
              ·
              {t.status ? t.status[0].toUpperCase() + t.status.slice(1) : '—'}
              ·
              {t.sla_due_at ? new Date(t.sla_due_at).toLocaleDateString() : '—'}
            </div>
            <a href={`#/tickets/${t.id}`} className="row-title">
              {t.title}
            </a>
            <div className="muted small">
              Created {new Date(t.created_at).toLocaleDateString()}
            </div>
          </li>
        ))}
      </ul>
    );
  }

  // ---- Helper: render assets section ----
  function renderAssets() {
    if (assetLoading) {
      return <EmptyState title="Loading assets..." hint="Please wait…" />;
    }
    if (assetError) {
      return <EmptyState title="Error" hint={assetError} />;
    }
    if (assets.length === 0) {
      return <EmptyState
        title="No assets"
        hint="You have no assigned assets. Contact IT if you need one."
      />;
    }
    return (
      <ul className="mini-list">
        {assets.map((a) => (
          <li key={a.id} className="mini-item">
            <a href={`#/assets/${a.id}`} className="mini-link">
              {a.asset_tag} – {a.name || '—'}
            </a>
            <div className="mini-desc">
              Status: {a.status || '—'}
            </div>
          </li>
        ))}
      </ul>
    );
  }

  // ---- Helper: render knowledge-base section ----
  function renderKb() {
    if (kbLoading) {
      return <EmptyState title="Loading articles..." hint="Please wait…" />;
    }
    if (kbError) {
      return <EmptyState title="Error" hint={kbError} />;
    }
    if (kbResults.length === 0) {
      return <EmptyState
        title="No articles found"
        hint="Try a different keyword or browse categories."
      />;
    }
    return (
      <ul className="note-list">
        {kbResults.map((a) => (
          <li key={a.id} className="is-unread">
            <div className="notif-title is-strong">{a.title}</div>
            <div className="muted small">
              {a.category ? `Category: ${a.category.name}` : ''}
              {a.tags?.length && (
                <span>
                  {Array.from(a.tags.values() || []).map((t) => (
                    <span key={t.slug} className="muted small tag"
                      >#{t.name}</span
                    >
                  ))}
                </span>
              )}
            </div>
            <div className="muted small">
              Created {new Date(a.created_at).toLocaleDateString()}
            </div>
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                alert(`Article: ${a.title}\n\n${a.content?.slice(0, 200)}…`);
              }}
            >
              Read article
            </a>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <Panel>
      <PanelHeader>
        <h3>Self‑Service</h3>
        <p className="muted small">
          Welcome, {user.employee_id} ({user.role.replace(/_/g, ' ')}).
        </p>
      </PanelHeader>

      <PanelPad>
        {/* Notification area */}
        <div className="mb-4">
          <NotifBadge />
          <button
            className="btn-ghost"
            onClick={loadTickets}
            title="Refresh tickets"
            style={{ marginLeft: 'var(--sp-2)' }}
          >
            Refresh
          </button>
          <button
            className="btn-secondary"
            disabled={true}
            style={{ marginLeft: 'var(--sp-2)' }}
            title="Mark all as read"
          >
            Mark all as read
          </button>
        </div>

        {/* My Tickets */}
        <Panel>
          <PanelHeader>
            <h4>My Tickets</h4>
            <Link
              className="link-small"
              href="#/tickets"
              style={{ marginBottom: 'var(--sp-2)' }}
              title="View all tickets in the system"
            >
              Browse all tickets
            </Link>
          </PanelHeader>
          {renderTickets()}
        </Panel>

        {/* My Assets */}
        <Panel>
          <PanelHeader>
            <h4>My Assets</h4>
            <Link
              className="link-small"
              href="#/assets"
              style={{ marginBottom: 'var(--sp-2)' }}
              title="View all assets in the system"
            >
              Browse all assets
            </Link>
          </PanelHeader>
          {renderAssets()}
        </Panel>

        {/* Knowledge Base */}
        <Panel>
          <PanelHeader>
            <h4>Knowledge Base</h4>
            <div className="filter-bar" role="search">
              <input
                className="input grow"
                value={kbQuery}
                onChange={(e) => {
                  setKbQuery(e.target.value);
                  loadKb();
                }}
                placeholder="Search articles…"
                aria-label="Search knowledge base"
              />
            </div>
          </PanelHeader>
          {renderKb()}
        </Panel>
      </PanelPad>
    </Panel>
  );
}