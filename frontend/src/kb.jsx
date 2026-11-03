import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, DataTable, EmptyState, Field, Modal, PageHeader, Pager,
  TableControls, useSort, useTableColumns,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

const KB_STATUSES = ['', 'draft', 'pending_review', 'approved', 'published', 'archived'];

const KB_STATUS_LABELS = {
  draft: 'Draft',
  pending_review: 'Pending review',
  approved: 'Approved',
  published: 'Published',
  archived: 'Archived',
};

/** Human-readable label for KB article status. */
function kbStatusLabel(s) {
  return KB_STATUS_LABELS[s] ?? s;
}

function fmtDate(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return '—';
  }
}

/** Extract query parameters from the hash route (e.g. compare?from=1&to=2). */
function hashQuery() {
  const raw = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(raw);
}

function isConflict(e) {
  return e?.response?.status === 409;
}

function conflictMessage(e) {
  const data = e?.response?.data;
  if (data && typeof data === 'object' && data.detail) return String(data.detail);
  return 'Another user modified this article. Reload the latest version and try again.';
}

function LoadingRows({ n = 4 }) {
  return (
    <div className="muted" role="status">
      <span className="spinner" aria-hidden="true" />Loading…
      <span className="sr-only">Loading {n} rows</span>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="error-summary" role="alert">
      {message}
      {onRetry && <button type="button" className="btn-small" onClick={onRetry}>Retry</button>}
    </div>
  );
}

/** Management page for knowledge-base articles (IT staff only).
 *
 * Lists articles with status + search filters, supports create/edit and
 * links to the pending-review queue and per-article revision history.
 */
export function KnowledgeBase() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [f, setF] = useState({ q: '', status: '' });
  const [sort, changeSort, orderingParam] = useSort();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [formMsg, setFormMsg] = useState('');
  const [formConflict, setFormConflict] = useState(false);
  const [pendingCount, setPendingCount] = useState(null);
  const [categories, setCategories] = useState([]);
  const [tags, setTags] = useState([]);
  const [refDataLoading, setRefDataLoading] = useState(false);

  const KB_COLUMNS = [
    { key: 'title', label: 'Title', render: (a) => <a className="row-title" href={`#/kb/${a.id}`}>{a.title}</a> },
    { key: 'status', label: 'Status', sortable: 'status', render: (a) => <Badge kind="status" value={a.status} label={kbStatusLabel(a.status)} /> },
    { key: 'revision', label: 'Revision', sortable: 'revision_number', render: (a) => `r${a.revision_number ?? 0}` },
    { key: 'category', label: 'Category', render: (a) => a.category_name ?? <span className="cell-muted">—</span> },
    { key: 'tags', label: 'Tags', render: (a) => (a.tags && a.tags.length ? a.tags.map((t) => t.name).join(', ') : <span className="cell-muted">—</span>) },
    { key: 'author', label: 'Author', render: (a) => a.author_name ?? <span className="cell-muted">—</span> },
    { key: 'views', label: 'Views', sortable: 'view_count', render: (a) => String(a.view_count ?? 0) },
    { key: 'created', label: 'Created', sortable: 'created_at', render: (a) => a.created_at ? new Date(a.created_at).toLocaleDateString() : '-' },
    {
      key: 'actions',
      label: 'Actions',
      render: (a) => (isStaff ? (
        <div className="row-gap">
          <button type="button" className="btn-small" onClick={() => openForm(a)}>Edit</button>
          <a className="btn-small" href={`#/kb/${a.id}/revisions`}>History</a>
        </div>
      ) : null),
    },
  ];

  const { visibleColumns: visibleKbColumns, toggleColumn: toggleKbColumn, resetColumns: resetKbColumns, tableVisible: kbTableVisible, toggleTable: toggleKbTable } = useTableColumns(
    'kb',
    KB_COLUMNS.map((c) => c.key),
    ['title', 'status', 'revision', 'category', 'tags', 'author', 'views', 'created', 'actions'],
  );
  const kbColumns = KB_COLUMNS.filter((c) => visibleKbColumns.has(c.key));

  const loadRefData = async () => {
    setRefDataLoading(true);
    try {
      const [cr, tr] = await Promise.all([
        api.get('/assets/knowledge-base-categories/'),
        api.get('/assets/knowledge-base-tags/'),
      ]);
      setCategories(cr.data.results ?? cr.data ?? []);
      setTags(tr.data.results ?? tr.data ?? []);
    } catch {
      // Non-fatal: form shows empty dropdowns.
    } finally {
      setRefDataLoading(false);
    }
  };

  const loadPendingCount = async () => {
    if (!isStaff) return;
    try {
      const r = await api.get('/assets/knowledge-base/pending_review/');
      setPendingCount((r.data.results ?? r.data ?? []).length);
    } catch {
      setPendingCount(null);
    }
  };

  const buildUrl = (over = {}, sortOverride) => {
    const p = new URLSearchParams();
    const merged = { ...f, ...over };
    for (const k of ['q', 'status']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam(sortOverride);
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    return `/assets/knowledge-base/${qs ? `?${qs}` : ''}`;
  };

  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setListError('Could not load knowledge-base articles.');
    } finally {
      setLoading(false);
    }
  };

  const applyFilters = (patch) => {
    const merged = { ...f, ...patch };
    setF(merged);
    const p = new URLSearchParams();
    for (const k of ['q', 'status']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/assets/knowledge-base/${qs ? `?${qs}` : ''}`);
  };

  const changeKbSort = (field) => {
    const nextSort = changeSort(field);
    loadUrl(buildUrl({}, nextSort));
  };

  // ---- Article create/edit form ----

  const EMPTY_FORM = {
    title: '', slug: '', summary: '', category: '', tags: [], content: '',
    status: 'draft', change_note: '', version: null,
  };
  const [form, setForm] = useState(EMPTY_FORM);
  const [tagInput, setTagInput] = useState('');

  const setField = (k) => (v) => setForm((p) => ({ ...p, [k]: v }));

  const openForm = (article = null) => {
    setEditing(article ? { id: article.id, title: article.title, version: article.version } : null);
    setForm(article ? {
      title: article.title ?? '', slug: article.slug ?? '',
      summary: article.summary ?? '',
      category: article.category?.code ?? '',
      tags: (article.tags ?? []).map((t) => t.slug),
      content: article.content ?? '', status: article.status ?? 'draft',
      change_note: '', version: article.version,
    } : EMPTY_FORM);
    setFormError('');
    setFormMsg('');
    setFormConflict(false);
    setShowForm(true);
  };

  const closeForm = () => { setShowForm(false); setEditing(null); };

  const reloadAfterConflict = async () => {
    setShowForm(false);
    setEditing(null);
    setFormConflict(false);
    await loadUrl(buildUrl());
  };

  const saveArticle = async (ev) => {
    ev.preventDefault();
    if (formBusy) return;
    setFormBusy(true);
    setFormError('');
    setFormMsg('');
    setFormConflict(false);
    const url = editing ? `/assets/knowledge-base/${editing.id}/` : '/assets/knowledge-base/';
    const method = editing ? 'patch' : 'post';
    const payload = {
      title: form.title.trim(),
      slug: form.slug.trim(),
      summary: form.summary,
      category: form.category || null,
      tags: form.tags.filter(Boolean),
      content: form.content,
      status: form.status || 'draft',
      change_note: form.change_note.trim(),
    };
    if (editing && form.version != null) payload.version = form.version;
    try {
      const r = await api[method](url, payload);
      setFormMsg(`Article "${r.data.title}" saved.`);
      setEditing(null);
      setShowForm(false);
      await loadRefData();
      await loadUrl(buildUrl());
      await loadPendingCount();
    } catch (e) {
      if (isConflict(e)) {
        setFormConflict(true);
        setFormError(conflictMessage(e));
      } else {
        setFormError(parseApiError(e).global || 'Could not save article.');
      }
    } finally {
      setFormBusy(false);
    }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t || form.tags.includes(t)) return;
    setForm((p) => ({ ...p, tags: [...p.tags, t] }));
    setTagInput('');
  };

  const removeTag = (slug) => {
    setForm((p) => ({ ...p, tags: p.tags.filter((s) => s !== slug) }));
  };

  useEffect(() => { loadRefData(); loadPendingCount(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadUrl('/assets/knowledge-base/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filtersActive = () => !!(f.q || f.status);

  return (
    <div>
      <PageHeader
        title="Knowledge Base"
        sub={count != null ? `${count} article${count === 1 ? '' : 's'} in scope` : undefined}
        actions={<>
          {isStaff && (
            <a className="btn-ghost" href="#/kb/pending">
              Pending review{pendingCount ? ` (${pendingCount})` : ''}
            </a>
          )}
          {isStaff && <button type="button" className="btn-primary" onClick={() => openForm()}>+ New article</button>}
        </>}
      />
      {listError && <ErrorState message={listError} onRetry={() => loadUrl(buildUrl())} />}
      {formMsg && <div className="success-summary" role="status">{formMsg}</div>}

      {showForm && (
        <Modal title={editing ? 'Edit article' : 'New article'} onClose={closeForm} size="wide">
          <form onSubmit={saveArticle} noValidate>
            {formError && <div className="error-summary" role="alert">
              {formError}
              {formConflict && (
                <button type="button" className="btn-small" onClick={reloadAfterConflict}>Reload latest</button>
              )}
            </div>}
            <Field label="Title" required>
              <input id="kb-title" className="input" value={form.title} onChange={(e) => setField('title')(e.target.value)} placeholder="Article title" disabled={formBusy} maxLength={255} />
            </Field>
            <Field label="Slug" required hint="URL-friendly identifier, e.g. vpn-reset.">
              <input id="kb-slug" className="input" value={form.slug} onChange={(e) => setField('slug')(e.target.value)} placeholder="vpn-reset" disabled={formBusy} maxLength={255} />
            </Field>
            <Field label="Summary" hint="Short description shown in lists and search results.">
              <input id="kb-summary" className="input" value={form.summary} onChange={(e) => setField('summary')(e.target.value)} disabled={formBusy} />
            </Field>
            <Field label="Category">
              <select id="kb-category" className="input" value={form.category} onChange={(e) => setField('category')(e.target.value)} disabled={formBusy || refDataLoading}>
                <option value="">None</option>
                {categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Content" hint="Markdown-style article body.">
              <textarea id="kb-content" className="input" rows={10} value={form.content} onChange={(e) => setField('content')(e.target.value)} disabled={formBusy} />
            </Field>
            <Field label="Tags" hint="Add existing tag slugs or pick from the list.">
              <div className="row-gap" style={{ gap: 'var(--sp-1)', flexWrap: 'wrap', alignItems: 'center' }}>
                <input id="kb-tag" className="input input-auto" value={tagInput} onChange={(e) => setTagInput(e.target.value)} placeholder="Add tag…" disabled={formBusy} />
                <button type="button" className="btn-small" onClick={addTag} disabled={formBusy || !tagInput.trim()}>Add</button>
                <select
                  className="input input-auto" value="" disabled={formBusy}
                  aria-label="Existing tags"
                  onChange={(e) => {
                    const slug = e.target.value;
                    if (slug && !form.tags.includes(slug)) setForm((p) => ({ ...p, tags: [...p.tags, slug] }));
                  }}
                >
                  <option value="">Choose existing…</option>
                  {tags.filter((t) => !form.tags.includes(t.slug)).map((t) => (
                    <option key={t.slug} value={t.slug}>{t.name}</option>
                  ))}
                </select>
                {form.tags.map((t) => (
                  <span key={t} className="badge badge-gray" style={{ margin: '2px 4px 2px 0' }}>{t}<button type="button" className="btn-ghost btn-small" onClick={() => removeTag(t)} style={{ marginLeft: 6 }}>&times;</button></span>
                ))}
              </div>
            </Field>
            <Field label="Status">
              <select id="kb-status" className="input" value={form.status} onChange={(e) => setField('status')(e.target.value)} disabled={formBusy}>
                <option value="draft">Draft</option>
                <option value="pending_review">Pending review</option>
                <option value="approved">Approved</option>
                <option value="published">Published</option>
                <option value="archived">Archived</option>
              </select>
            </Field>
            {editing && (
              <Field label="Change note" hint="Optional description stored with the new revision.">
                <input id="kb-change-note" className="input" value={form.change_note} onChange={(e) => setField('change_note')(e.target.value)} disabled={formBusy} maxLength={500} />
              </Field>
            )}
            {refDataLoading && <div className="muted small">Loading categories and tags…</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={closeForm} disabled={formBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={formBusy || !form.title.trim()}>
                {formBusy ? 'Saving…' : (editing ? 'Save changes' : 'Create article')}
              </button>
            </div>
          </form>
        </Modal>
      )}

      <div className="filter-bar" role="search">
        <input
          className="input grow" value={f.q} onChange={(e) => applyFilters({ q: e.target.value })}
          placeholder="Search title, summary or content…" aria-label="Search knowledge base"
        />
        <select className="input" value={f.status} onChange={(e) => applyFilters({ status: e.target.value })} aria-label="Filter by status">
          <option value="">All statuses</option>
          {KB_STATUSES.filter(Boolean).map((s) => <option key={s} value={s}>{kbStatusLabel(s)}</option>)}
        </select>
        {filtersActive() && (
          <button type="button" className="btn-ghost" onClick={() => applyFilters({ q: '', status: '' })}>Clear filters</button>
        )}
      </div>

      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows /></div>
          : listError ? <div className="panel-pad"><ErrorState message={listError} onRetry={() => loadUrl(buildUrl())} /></div>
          : count === 0 ? <EmptyState title="No knowledge-base articles yet." hint="IT staff can create the first article with + New article." />
          : (<>
            <TableControls tableVisible={kbTableVisible} onToggleTable={toggleKbTable} columns={KB_COLUMNS} visible={visibleKbColumns} onToggleColumn={toggleKbColumn} onReset={resetKbColumns} />
            {kbTableVisible ? (
              <DataTable
                columns={kbColumns}
                rows={items}
                keyOf={(a) => a.id}
                sort={sort}
                onSort={changeKbSort}
                emptyTitle="No articles match."
                emptyHint="Adjust the search or status filter."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
    </div>
  );
}

/** Shared badges / metadata used by the detail and revision pages. */
function ReviewSummary({ article }) {
  if (!article.review_decision && !article.reviewed_by_name) return null;
  return (
    <div className="panel-section" data-testid="review-summary">
      <h4>Review</h4>
      <p>
        <strong>Decision:</strong> {article.review_decision || 'not reviewed'}
        {article.reviewed_by_name ? <> • <strong>Reviewer:</strong> {article.reviewed_by_name}</> : null}
        {article.reviewed_at ? <> • <strong>Reviewed:</strong> {fmtDate(article.reviewed_at)}</> : null}
      </p>
      {article.review_comment && <p><strong>Comment:</strong> {article.review_comment}</p>}
      {article.submitted_at && <p className="muted small">Submitted for review {fmtDate(article.submitted_at)}</p>}
    </div>
  );
}

/** Read-only detail view for a single knowledge-base article. */
export function KnowledgeBaseDetail({ id }) {
  const { user, isStaff } = useAuth();
  const [article, setArticle] = useState(null);
  const [revisions, setRevisions] = useState([]);
  const [revLoading, setRevLoading] = useState(false);
  const [revError, setRevError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [reviewComment, setReviewComment] = useState('');
  const [restoreFor, setRestoreFor] = useState(null);
  const [compareA, setCompareA] = useState('');
  const [compareB, setCompareB] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    setConflict(false);
    try {
      const r = await api.get(`/assets/knowledge-base/${id}/`);
      setArticle(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load article.');
    } finally {
      setLoading(false);
    }
  };

  const loadRevisions = async () => {
    if (!isStaff) return;
    setRevLoading(true);
    setRevError('');
    try {
      const r = await api.get(`/assets/knowledge-base/${id}/revisions/`);
      const rows = r.data.results ?? r.data ?? [];
      setRevisions(rows);
    } catch (e) {
      setRevError(parseApiError(e).global || 'Could not load revision history.');
    } finally {
      setRevLoading(false);
    }
  };

  const handleActionError = (e, fallback) => {
    if (isConflict(e)) {
      setConflict(true);
      setError(conflictMessage(e));
    } else {
      setError(parseApiError(e).global || fallback);
    }
  };

  const postAction = async (path, body, successMessage) => {
    if (!article || busy) return null;
    setBusy(true);
    setError('');
    setConflict(false);
    setMsg('');
    try {
      const payload = { ...(body ?? {}) };
      if (payload.version == null) payload.version = article.version;
      const r = await api.post(`/assets/knowledge-base/${id}/${path}/`, payload);
      setArticle(r.data.article ?? r.data);
      setMsg(successMessage);
      await loadRevisions();
      return r.data;
    } catch (e) {
      handleActionError(e, 'Could not update the article.');
      return null;
    } finally {
      setBusy(false);
    }
  };

  const restoreRevision = async () => {
    if (!restoreFor) return;
    const source = restoreFor.revision_number;
    const result = await postAction(
      'restore', { revision_number: source }, `Restored revision ${source}.`);
    if (result?.revision) {
      setMsg(`Restored revision ${source} as revision ${result.revision.revision_number}. Existing revisions were kept.`);
    }
    setRestoreFor(null);
  };

  useEffect(() => { load(); loadRevisions(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const orderedRevisions = useMemo(
    () => [...revisions].sort((a, b) => b.revision_number - a.revision_number),
    [revisions],
  );

  const goCompare = () => {
    if (!compareA || !compareB) return;
    const from = Math.min(Number(compareA), Number(compareB));
    const to = Math.max(Number(compareA), Number(compareB));
    location.hash = `#/kb/${id}/compare?from=${from}&to=${to}`;
  };

  let statusActions = null;
  if (article && isStaff && user) {
    if (article.status === 'draft' || article.status === 'archived') {
      statusActions = (
        <div className="row-end">
          <button type="button" className="btn-primary" onClick={() => postAction('submit_review', {}, 'Article submitted for review.')} disabled={busy}>
            Submit for review
          </button>
          <button type="button" className="btn-ghost" onClick={() => postAction('archive', {}, 'Article archived.')} disabled={busy}>
            Archive
          </button>
        </div>
      );
    } else if (article.status === 'pending_review') {
      statusActions = (
        <div className="row-end">
          <button type="button" className="btn-primary" onClick={() => { setReviewComment(''); setApproveOpen(true); }} disabled={busy}>
            Approve
          </button>
          <button type="button" className="btn-danger" onClick={() => { setReviewComment(''); setRejectOpen(true); }} disabled={busy}>
            Reject
          </button>
        </div>
      );
    } else if (article.status === 'approved') {
      statusActions = (
        <div className="row-end">
          <button type="button" className="btn-primary" onClick={() => postAction('publish', {}, 'Article published.')} disabled={busy}>
            Publish
          </button>
          <button type="button" className="btn-ghost" onClick={() => postAction('archive', {}, 'Article archived.')} disabled={busy}>
            Archive
          </button>
        </div>
      );
    } else if (article.status === 'published') {
      statusActions = (
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={() => postAction('archive', {}, 'Article archived.')} disabled={busy}>
            Archive
          </button>
        </div>
      );
    }
  }

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading article…
      </p>
    );
  }
  if (error && !article) {
    return (
      <div className="form-wrap">
        <ErrorState message={error} onRetry={load} />
        <p><a className="back-link" href="#/kb">← Back to knowledge base</a></p>
      </div>
    );
  }
  if (!article) {
    return (
      <div className="form-wrap">
        <div className="error-summary" role="alert">Article not found.</div>
        <p><a className="back-link" href="#/kb">← Back to knowledge base</a></p>
      </div>
    );
  }

  return (
    <div className="form-wrap">
      <PageHeader
        title={article.title}
        sub={`Status: ${kbStatusLabel(article.status)} • Revision r${article.revision_number ?? 0} • Views: ${article.view_count ?? 0} • ${article.author_name ?? 'Unknown author'}`}
        actions={
          <div>
            <a className="btn-ghost" href="#/kb">← Back to knowledge base</a>
            {statusActions}
          </div>
        }
      />
      {error && (
        <div className="error-summary" role="alert">
          {error}
          {conflict && <button type="button" className="btn-small" onClick={() => { load(); loadRevisions(); }}>Reload latest</button>}
        </div>
      )}
      {msg && <div className="success-summary" role="status">{msg}</div>}

      <div className="panel-pad">
        <div className="panel-section">
          <h4>Content</h4>
          {article.summary && <p className="muted">{article.summary}</p>}
          <div className="kb-content" style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>{article.content || <span className="cell-muted">No content.</span>}</div>
        </div>
        <div className="panel-section">
          <h4>Details</h4>
          <div className="row-gap">
            <span><strong>Slug:</strong> {article.slug}</span>
            <span className="spacer" />
            <span><strong>Category:</strong> {article.category_name ?? article.category?.name ?? 'None'}</span>
          </div>
          <div className="row-gap">
            <span><strong>Tags:</strong> {(article.tags ?? []).map((t) => t.name).join(', ') || 'None'}</span>
          </div>
          <div className="row-gap">
            <span><strong>Created:</strong> {article.created_at ? new Date(article.created_at).toLocaleDateString() : '—'}</span>
            <span className="spacer" />
            <span><strong>Updated:</strong> {article.updated_at ? new Date(article.updated_at).toLocaleDateString() : '—'}</span>
          </div>
        </div>
        <ReviewSummary article={article} />

        {isStaff && (
          <div className="panel-section" data-testid="revision-history">
            <h4>Revision history</h4>
            {revLoading ? <LoadingRows /> : revError ? (
              <ErrorState message={revError} onRetry={loadRevisions} />
            ) : orderedRevisions.length === 0 ? (
              <EmptyState title="No revisions yet." hint="Saving an edit creates the first revision snapshot." />
            ) : (
              <>
                <div className="row-gap" style={{ gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                  {orderedRevisions.map((rev) => (
                    <label key={rev.id} className="rev-selector">
                      <input
                        type="checkbox"
                        checked={compareA === String(rev.revision_number)}
                        onChange={() => setCompareA(compareA === String(rev.revision_number) ? '' : String(rev.revision_number))}
                        aria-label={`Select revision ${rev.revision_number} as comparison A`}
                      />
                      r{rev.revision_number}
                      <input
                        type="checkbox"
                        checked={compareB === String(rev.revision_number)}
                        onChange={() => setCompareB(compareB === String(rev.revision_number) ? '' : String(rev.revision_number))}
                        aria-label={`Select revision ${rev.revision_number} as comparison B`}
                      />
                    </label>
                  ))}
                  <button type="button" className="btn-small" onClick={goCompare} disabled={!compareA || !compareB || compareA === compareB}>
                    Compare selected
                  </button>
                </div>
                <ul className="rev-list">
                  {orderedRevisions.map((rev) => (
                    <li key={rev.id}>
                      <div className="row-gap">
                        <a className="row-title" href={`#/kb/${id}/revisions/${rev.revision_number}`}>Revision {rev.revision_number}</a>
                        {rev.is_current && <span className="badge badge-blue">Current</span>}
                        {rev.is_current_published && <span className="badge badge-green">Current published</span>}
                        {rev.restored_from_revision && <span className="badge badge-purple">Restored from r{rev.restored_from_revision}</span>}
                      </div>
                      <div className="muted small">
                        {rev.editor_name || 'Unknown editor'} • {fmtDate(rev.created_at)} • {rev.change_note || 'No change note'}
                      </div>
                      <div className="row-gap">
                        <a className="btn-small" href={`#/kb/${id}/revisions/${rev.revision_number}`}>View</a>
                        <a
                          className="btn-small"
                          href={`#/kb/${id}/compare?from=${Math.min(rev.revision_number, article.revision_number)}&to=${Math.max(rev.revision_number, article.revision_number)}`}
                        >
                          Compare with current
                        </a>
                        <button type="button" className="btn-small" onClick={() => setRestoreFor(rev)} disabled={busy}>
                          Restore
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>

      {approveOpen && (
        <Modal title="Approve article" onClose={() => setApproveOpen(false)}>
          <Field label="Review comment" hint="Optional note stored with the approval.">
            <textarea className="input" rows={4} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)} aria-label="Approval comment" />
          </Field>
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setApproveOpen(false)}>Cancel</button>
            <button
              type="button" className="btn-primary" disabled={busy}
              onClick={async () => {
                const done = await postAction('approve', { comment: reviewComment }, 'Article approved.');
                if (done) setApproveOpen(false);
              }}
            >
              Approve
            </button>
          </div>
        </Modal>
      )}

      {rejectOpen && (
        <Modal title="Reject article" onClose={() => setRejectOpen(false)}>
          <Field label="Reason" required hint="Explain what needs to change before resubmission.">
            <textarea className="input" rows={4} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)} aria-label="Rejection reason" />
          </Field>
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setRejectOpen(false)}>Cancel</button>
            <button
              type="button" className="btn-danger" disabled={busy || !reviewComment.trim()}
              onClick={async () => {
                const done = await postAction('reject', { comment: reviewComment }, 'Article rejected and returned to draft.');
                if (done) setRejectOpen(false);
              }}
            >
              Reject
            </button>
          </div>
        </Modal>
      )}

      {restoreFor && (
        <ConfirmDialog
          title="Restore revision"
          message={`Restore revision ${restoreFor.revision_number}? A new revision will be created and the current article content will be updated. Newer revisions are kept.`}
          confirmLabel="Restore revision"
          busy={busy}
          onConfirm={restoreRevision}
          onCancel={() => setRestoreFor(null)}
        />
      )}
    </div>
  );
}

/** Full revision history for one article. */
export function KnowledgeBaseRevisions({ id }) {
  const { isStaff } = useAuth();
  const [article, setArticle] = useState(null);
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [restoreFor, setRestoreFor] = useState(null);
  const [selected, setSelected] = useState([]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [ar, rr] = await Promise.all([
        api.get(`/assets/knowledge-base/${id}/`),
        api.get(`/assets/knowledge-base/${id}/revisions/`),
      ]);
      setArticle(ar.data);
      setRevisions(rr.data.results ?? rr.data ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load revision history.');
    } finally {
      setLoading(false);
    }
  };

  const toggleSelected = (number) => {
    setSelected((prev) => {
      if (prev.includes(number)) return prev.filter((n) => n !== number);
      if (prev.length >= 2) return [prev[1], number];
      return [...prev, number];
    });
  };

  const restore = async () => {
    if (!restoreFor || !article) return;
    setBusy(true);
    setError('');
    try {
      const r = await api.post(`/assets/knowledge-base/${id}/restore/`, {
        revision_number: restoreFor.revision_number,
        version: article.version,
      });
      setMsg(`Restored revision ${restoreFor.revision_number} as revision ${r.data.revision?.revision_number}. Existing revisions are unchanged.`);
      setRestoreFor(null);
      await load();
    } catch (e) {
      if (isConflict(e)) {
        setError(conflictMessage(e));
      } else {
        setError(parseApiError(e).global || 'Could not restore this revision.');
      }
      setRestoreFor(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isStaff) {
    return <div className="form-wrap"><div className="error-summary" role="alert">You do not have permission to view revision history.</div></div>;
  }
  if (loading) {
    return <p className="page-loading" role="status"><span className="spinner" aria-hidden="true" />Loading revision history…</p>;
  }
  if (error && !article) {
    return <div className="form-wrap"><ErrorState message={error} onRetry={load} /></div>;
  }

  const sorted = [...revisions].sort((a, b) => b.revision_number - a.revision_number);
  return (
    <div className="form-wrap">
      <PageHeader
        title={`Revision history${article ? ` — ${article.title}` : ''}`}
        sub={article ? `Current revision r${article.revision_number} • ${kbStatusLabel(article.status)}` : undefined}
        actions={<>
          <a className="btn-ghost" href={`#/kb/${id}`}>← Back to article</a>
          <button
            type="button" className="btn-primary"
            disabled={selected.length !== 2}
            onClick={() => {
              const [a, b] = [...selected].sort((x, y) => x - y);
              location.hash = `#/kb/${id}/compare?from=${a}&to=${b}`;
            }}
          >
            Compare selected
          </button>
        </>}
      />
      {error && <ErrorState message={error} onRetry={load} />}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      <div className="panel">
        {sorted.length === 0 ? (
          <EmptyState title="No revisions yet." hint="Editing this article creates immutable revision snapshots." />
        ) : (
          <ul className="rev-list">
            {sorted.map((rev) => (
              <li key={rev.id}>
                <div className="row-gap">
                  <input
                    type="checkbox"
                    checked={selected.includes(rev.revision_number)}
                    onChange={() => toggleSelected(rev.revision_number)}
                    aria-label={`Select revision ${rev.revision_number}`}
                  />
                  <a className="row-title" href={`#/kb/${id}/revisions/${rev.revision_number}`}>Revision {rev.revision_number}</a>
                  {rev.is_current && <span className="badge badge-blue">Current</span>}
                  {rev.is_current_published && <span className="badge badge-green">Current published</span>}
                  {rev.restored_from_revision && <span className="badge badge-purple">Restored from r{rev.restored_from_revision}</span>}
                </div>
                <div className="muted small">
                  {rev.editor_name || 'Unknown editor'} • {fmtDate(rev.created_at)} • {rev.change_note || 'No change note'}
                </div>
                <div className="row-gap">
                  <a className="btn-small" href={`#/kb/${id}/revisions/${rev.revision_number}`}>View</a>
                  <button type="button" className="btn-small" onClick={() => setRestoreFor(rev)} disabled={busy}>Restore</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      {restoreFor && (
        <ConfirmDialog
          title="Restore revision"
          message={`Restore revision ${restoreFor.revision_number}? A new revision will be created; newer revisions remain available.`}
          confirmLabel="Restore revision"
          busy={busy}
          onConfirm={restore}
          onCancel={() => setRestoreFor(null)}
        />
      )}
    </div>
  );
}

/** Read-only view of one historical revision. */
export function KnowledgeBaseRevisionDetail({ id, number }) {
  const { isStaff } = useAuth();
  const [revision, setRevision] = useState(null);
  const [article, setArticle] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [confirmRestore, setConfirmRestore] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [rr, ar] = await Promise.all([
        api.get(`/assets/knowledge-base/${id}/revisions/${number}/`),
        api.get(`/assets/knowledge-base/${id}/`),
      ]);
      setRevision(rr.data);
      setArticle(ar.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load this revision.');
    } finally {
      setLoading(false);
    }
  };

  const restore = async () => {
    if (!revision || !article) return;
    setBusy(true);
    setError('');
    try {
      const r = await api.post(`/assets/knowledge-base/${id}/restore/`, {
        revision_number: revision.revision_number,
        version: article.version,
      });
      setMsg(`Restored revision ${revision.revision_number} as revision ${r.data.revision?.revision_number}.`);
      setArticle(r.data.article);
      setConfirmRestore(false);
    } catch (e) {
      setError(isConflict(e) ? conflictMessage(e) : (parseApiError(e).global || 'Could not restore this revision.'));
      setConfirmRestore(false);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); }, [id, number]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isStaff) {
    return <div className="form-wrap"><div className="error-summary" role="alert">You do not have permission to view revisions.</div></div>;
  }
  if (loading) {
    return <p className="page-loading" role="status"><span className="spinner" aria-hidden="true" />Loading revision…</p>;
  }
  if (error && !revision) {
    return (
      <div className="form-wrap">
        <ErrorState message={error} onRetry={load} />
        <p><a className="back-link" href={`#/kb/${id}`}>← Back to current article</a></p>
      </div>
    );
  }

  return (
    <div className="form-wrap">
      <PageHeader
        title={`Revision ${number}${revision ? ` — ${revision.title}` : ''}`}
        sub={revision ? `${revision.editor_name || 'Unknown editor'} • ${fmtDate(revision.created_at)}` : undefined}
        actions={<>
          <a className="btn-ghost" href={`#/kb/${id}`}>← Back to current article</a>
          <a className="btn-ghost" href={`#/kb/${id}/revisions`}>All revisions</a>
          <button type="button" className="btn-primary" onClick={() => setConfirmRestore(true)} disabled={busy}>
            Restore this revision
          </button>
        </>}
      />
      {error && <ErrorState message={error} onRetry={load} />}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      {revision && (
        <div className="panel-pad">
          <div className="panel-section">
            <h4>Snapshot details</h4>
            <div className="row-gap"><span><strong>Title:</strong> {revision.title}</span></div>
            <div className="row-gap"><span><strong>Slug:</strong> {revision.slug}</span></div>
            <div className="row-gap"><span><strong>Status at snapshot:</strong> {kbStatusLabel(revision.status)}</span></div>
            <div className="row-gap"><span><strong>Category:</strong> {revision.category_name || 'None'}</span></div>
            <div className="row-gap"><span><strong>Tags:</strong> {(revision.tags ?? []).map((t) => t.name).join(', ') || 'None'}</span></div>
            <div className="row-gap"><span><strong>Change note:</strong> {revision.change_note || '—'}</span></div>
            {revision.restored_from_revision && <div className="row-gap"><span><strong>Restored from:</strong> revision {revision.restored_from_revision}</span></div>}
            {revision.is_current && <p><span className="badge badge-blue">Current revision</span></p>}
          </div>
          <div className="panel-section">
            <h4>Summary</h4>
            <p>{revision.summary || <span className="cell-muted">No summary.</span>}</p>
          </div>
          <div className="panel-section">
            <h4>Content</h4>
            <div className="kb-content" style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>
              {revision.content || <span className="cell-muted">No content.</span>}
            </div>
          </div>
        </div>
      )}
      {confirmRestore && revision && (
        <ConfirmDialog
          title="Restore revision"
          message={`Restore revision ${revision.revision_number}? A new revision will be created. Newer revisions stay available.`}
          confirmLabel="Restore revision"
          busy={busy}
          onConfirm={restore}
          onCancel={() => setConfirmRestore(false)}
        />
      )}
    </div>
  );
}

function DiffParts({ parts }) {
  return (
    <span>
      {(parts ?? []).map((part, i) => (
        <span
          key={i}
          className={part.type === 'added' ? 'diff-add' : part.type === 'removed' ? 'diff-remove' : undefined}
        >
          {part.text}
        </span>
      ))}
    </span>
  );
}

/** Compare two revisions of one article. */
export function KnowledgeBaseCompare({ id }) {
  const { isStaff } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const params = hashQuery();
  const from = params.get('from');
  const to = params.get('to');

  const load = async () => {
    if (!from || !to) {
      setError('Choose two revisions to compare.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const r = await api.get(`/assets/knowledge-base/${id}/compare/`, {
        params: { from_revision: from, to_revision: to },
      });
      setData(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not compare these revisions.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id, from, to]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isStaff) {
    return <div className="form-wrap"><div className="error-summary" role="alert">You do not have permission to compare revisions.</div></div>;
  }
  if (loading) {
    return <p className="page-loading" role="status"><span className="spinner" aria-hidden="true" />Comparing revisions…</p>;
  }
  if (error) {
    return (
      <div className="form-wrap">
        <ErrorState message={error} onRetry={load} />
        <p><a className="back-link" href={`#/kb/${id}/revisions`}>← Back to revision history</a></p>
      </div>
    );
  }
  if (!data) return null;

  const fields = data.fields ?? {};
  const noChanges = ['title', 'summary', 'content', 'category', 'tags']
    .every((key) => !fields[key]?.changed);

  return (
    <div className="form-wrap">
      <PageHeader
        title={`Compare revisions ${data.older.revision_number} → ${data.newer.revision_number}`}
        sub={noChanges ? 'No content differences between these revisions.' : 'Removed content is highlighted in red, added content in green.'}
        actions={<>
          <a className="btn-ghost" href={`#/kb/${id}/revisions`}>← Back to revision history</a>
          <a className="btn-ghost" href={`#/kb/${id}`}>Current article</a>
        </>}
      />
      {noChanges && <div className="info-summary" role="status">These revisions have identical content.</div>}

      <div className="panel-pad">
        <div className="panel-section">
          <h4>Title</h4>
          {fields.title?.changed
            ? <div className="diff-block"><DiffParts parts={fields.title.parts} /></div>
            : <p>{data.newer.title}</p>}
        </div>
        <div className="panel-section">
          <h4>Summary</h4>
          {fields.summary?.changed
            ? <div className="diff-block"><DiffParts parts={fields.summary.parts} /></div>
            : <p>{data.newer.summary || <span className="cell-muted">No summary.</span>}</p>}
        </div>
        <div className="panel-section">
          <h4>Category</h4>
          {fields.category?.changed
            ? <p><span className="diff-remove">{fields.category.old || 'None'}</span> → <span className="diff-add">{fields.category.new || 'None'}</span></p>
            : <p>{data.newer.category_name || 'None'}</p>}
        </div>
        <div className="panel-section">
          <h4>Tags</h4>
          {fields.tags?.changed
            ? <p><span className="diff-remove">{(fields.tags.old ?? []).join(', ') || 'None'}</span> → <span className="diff-add">{(fields.tags.new ?? []).join(', ') || 'None'}</span></p>
            : <p>{(data.newer.tags ?? []).map((t) => t.name).join(', ') || 'None'}</p>}
        </div>
        <div className="panel-section">
          <h4>Article body</h4>
          {fields.content?.changed ? (
            <div className="diff-block" role="table" aria-label="Article content differences">
              {(fields.content.lines ?? []).map((line, i) => (
                <div
                  key={i}
                  role="row"
                  className={`diff-line diff-line-${line.type}`}
                  data-testid={`diff-line-${line.type}`}
                >
                  <span className="diff-gutter" aria-hidden="true">
                    {line.type === 'added' ? '+' : line.type === 'removed' ? '−' : ' '}
                  </span>
                  <span className="diff-text">{line.text || ' '}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted">Article body unchanged.</p>}
        </div>
      </div>
    </div>
  );
}

/** Pending-review queue for reviewers (IT staff). */
export function KnowledgeBaseReviewQueue() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get('/assets/knowledge-base/pending_review/');
      setItems(r.data.results ?? r.data ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load the pending-review queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isStaff) {
    return <div className="form-wrap"><div className="error-summary" role="alert">You do not have permission to review articles.</div></div>;
  }
  if (loading) {
    return <p className="page-loading" role="status"><span className="spinner" aria-hidden="true" />Loading pending reviews…</p>;
  }

  return (
    <div className="form-wrap">
      <PageHeader
        title="Pending review"
        sub={`${items.length} article${items.length === 1 ? '' : 's'} awaiting review`}
        actions={<a className="btn-ghost" href="#/kb">← Back to knowledge base</a>}
      />
      {error && <ErrorState message={error} onRetry={load} />}
      <div className="panel">
        {items.length === 0 ? (
          <EmptyState title="Nothing pending review." hint="Articles submitted for review appear here." />
        ) : (
          <ul className="rev-list">
            {items.map((a) => (
              <li key={a.id}>
                <a className="row-title" href={`#/kb/${a.id}`}>{a.title}</a>
                <div className="muted small">
                  By {a.author_name || 'Unknown author'} • Submitted {fmtDate(a.submitted_at)} • r{a.revision_number}
                </div>
                <div className="row-gap">
                  <Badge kind="status" value={a.status} label={kbStatusLabel(a.status)} />
                  <a className="btn-small" href={`#/kb/${a.id}`}>Review details</a>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default KnowledgeBase;
