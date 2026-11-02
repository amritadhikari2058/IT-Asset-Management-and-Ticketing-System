import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, Field, Modal, PageHeader, Pager,
  TableControls, useSort, useTableColumns,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

const KB_STATUSES = ['', 'draft', 'published', 'archived'];

/** Human-readable label for KB article status. */
function kbStatusLabel(s) {
  const m = { draft: 'Draft', published: 'Published', archived: 'Archived' };
  return m[s] ?? s;
}

/** Management page for knowledge-base articles (IT staff only).
 *
 * Lists articles with status + search filters, supports create/edit/publish/
 * archive, and shows category/tag assignment per article.
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
  const [editing, setEditing] = useState(null); // {id} or null
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [formMsg, setFormMsg] = useState('');
  const [publishFor, setPublishFor] = useState(null);
  const [archiveFor, setArchiveFor] = useState(null);
  const [actionBusy, setActionBusy] = useState(null);
  const [categories, setCategories] = useState([]);
  const [tags, setTags] = useState([]);
  const [refDataLoading, setRefDataLoading] = useState(false);

  const KB_COLUMNS = [
    { key: 'title', label: 'Title', render: (a) => <a className="row-title" href={`#/kb/${a.id}`}>{a.title}</a> },
    { key: 'status', label: 'Status', sortable: 'status', render: (a) => <Badge kind="status" value={a.status} label={kbStatusLabel(a.status)} /> },
    { key: 'category', label: 'Category', render: (a) => a.category_name ?? <span className="cell-muted">—</span> },
    { key: 'tags', label: 'Tags', render: (a) => (a.tags && a.tags.length ? a.tags.map((t) => t.name).join(', ') : <span className="cell-muted">—</span>) },
    { key: 'author', label: 'Author', render: (a) => a.author_name ?? <span className="cell-muted">—</span> },
    { key: 'views', label: 'Views', sortable: 'view_count', render: (a) => String(a.view_count ?? 0) },
    { key: 'created', label: 'Created', sortable: 'created_at', render: (a) => a.created_at ? new Date(a.created_at).toLocaleDateString() : '-' },
  ];

  const { visibleColumns: visibleKbColumns, toggleColumn: toggleKbColumn, resetColumns: resetKbColumns, tableVisible: kbTableVisible, toggleTable: toggleKbTable } = useTableColumns(
    'kb',
    KB_COLUMNS.map((c) => c.key),
    ['title', 'status', 'category', 'tags', 'author', 'views', 'created'],
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
      // Non-fatal: form will show empty dropdowns.
    } finally {
      setRefDataLoading(false);
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

  const toggleStatus = async (article, targetStatus) => {
    if (actionBusy) return;
    setActionBusy(article.id);
    try {
      await api.patch(`/assets/knowledge-base/${article.id}/`, { status: targetStatus });
      setMsg(`${article.title} ${targetStatus}.`);
      await loadUrl(buildUrl());
    } catch (e) {
      setFormError(parseApiError(e).global || `Could not ${targetStatus} article.`);
    } finally {
      setActionBusy(null);
    }
  };

  const doArchive = (a) => {
    if (!confirm(`Archive "${a.title}"? Archived articles are hidden from employees.`)) return;
    toggleStatus(a, 'archived');
  };

  const doPublish = (a) => {
    if (!confirm(`Publish "${a.title}"? Published articles are visible to all employees.`)) return;
    toggleStatus(a, 'published');
  };

  // ---- Article create/edit form ----

  const [form, setForm] = useState({
    title: '', slug: '', category: '', tags: [], content: '', status: 'draft',
  });
  const [tagInput, setTagInput] = useState('');

  const setField = (k) => (v) => setForm((p) => ({ ...p, [k]: v }));

  const openForm = (article = null) => {
    setEditing(article ? { id: article.id } : null);
    setForm(article ? {
      title: article.title ?? '', slug: article.slug ?? '',
      category: article.category ?? '', tags: (article.tags ?? []).map((t) => t.slug),
      content: article.content ?? '', status: article.status ?? 'draft',
    } : { title: '', slug: '', category: '', tags: [], content: '', status: 'draft' });
    setFormError('');
    setFormMsg('');
    setShowForm(true);
  };

  const closeForm = () => { setShowForm(false); setEditing(null); };

  const saveArticle = async (ev) => {
    ev.preventDefault();
    if (formBusy) return;
    setFormBusy(true);
    setFormError('');
    setFormMsg('');
    const url = editing ? `/assets/knowledge-base/${editing.id}/` : '/assets/knowledge-base/';
    const method = editing ? 'patch' : 'post';
    try {
      const r = await api[method](url, {
        title: form.title.trim(),
        slug: form.slug.trim(),
        category: form.category || null,
        tags: form.tags.filter(Boolean),
        content: form.content,
        status: form.status || 'draft',
      });
      setFormMsg(`Article "${r.data.title}" saved.`);
      setEditing(null);
      setShowForm(false);
      await loadRefData();
      await loadUrl(buildUrl());
    } catch (e) {
      setFormError(parseApiError(e).global || 'Could not save article.');
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

  useEffect(() => { loadRefData(); }, []);
  useEffect(() => { loadUrl('/assets/knowledge-base/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <PageHeader
        title="Knowledge Base"
        sub={count != null ? `${count} article${count === 1 ? '' : 's'} in scope` : undefined}
        actions={<>
          {isStaff && <button type="button" className="btn-primary" onClick={() => openForm()}>+ New article</button>}
        </>}
      />
      {listError && <div className="error-summary" role="alert">{listError}</div>}
      {formMsg && <div className="success-summary" role="status">{formMsg}</div>}
      {formError && <div className="error-summary" role="alert">{formError}</div>}

      {showForm && (
        <Modal title={editing ? 'Edit article' : 'New article'} onClose={closeForm} size="wide">
          <form onSubmit={saveArticle} noValidate>
            <Field label="Title" required error={formError}>
              <input className="input" value={form.title} onChange={setField('title')} placeholder="Article title" disabled={formBusy} maxLength={255} />
            </Field>
            <Field label="Slug" required hint="URL-friendly identifier, e.g. vpn-reset.">
              <input className="input" value={form.slug} onChange={setField('slug')} placeholder="vpn-reset" disabled={formBusy} maxLength={255} />
            </Field>
            <Field label="Category">
              <select className="input" value={form.category} onChange={setField('category')} disabled={formBusy || refDataLoading}>
                <option value="">None</option>
                {categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Content" hint="Markdown-style article body.">
              <textarea className="input" rows={10} value={form.content} onChange={setField('content')} disabled={formBusy} />
            </Field>
            <Field label="Tags" hint="Comma-separated or pick existing.">
              <div className="row-gap" style={{ gap: 'var(--sp-1)', flexWrap: 'wrap', alignItems: 'center' }}>
                <input className="input input-auto" value={tagInput} onChange={(e) => setTagInput(e.target.value)} placeholder="Add tag…" disabled={formBusy} />
                <button type="button" className="btn-small" onClick={addTag} disabled={formBusy || !tagInput.trim()}>Add</button>
                {form.tags.map((t) => (
                  <span key={t} className="badge badge-gray" style={{ margin: '2px 4px 2px 0' }}>{t}<button type="button" className="btn-ghost btn-small" onClick={() => removeTag(t)} style={{ marginLeft: 6 }}>&times;</button></span>
                ))}
              </div>
            </Field>
            <Field label="Status">
              <select className="input" value={form.status} onChange={setField('status')} disabled={formBusy}>
                <option value="draft">Draft</option>
                <option value="published">Published</option>
                <option value="archived">Archived</option>
              </select>
            </Field>
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
          placeholder="Search title or content…" aria-label="Search knowledge base"
        />
        <select className="input" value={f.status} onChange={(e) => applyFilters({ status: e.target.value })} aria-label="Filter by status">
          <option value="">All statuses</option>
          {KB_STATUSES.filter(Boolean).map((s) => <option key={s} value={s}>{kbStatusLabel(s)}</option>)}
        </select>
        {filtersActive() && (
          <button type="button" className="btn-ghost" onClick={() => setF({ q: '', status: '' })}>Clear filters</button>
        )}
      </div>

      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl(buildUrl())}>Retry</button></div></div>
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

      {/* Per-row actions rendered below the table via a compact action column is
         not supported by DataTable, so expose publish/archive through the
         article detail page instead. */}
    </div>
  );

  function filtersActive() {
    return !!(f.q || f.status);
  }
}

/** Read-only detail view for a single knowledge-base article. */
export function KnowledgeBaseDetail({ id }) {
  const { user } = useAuth();
  const [article, setArticle] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get(`/assets/knowledge-base/${id}/`);
      setArticle(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load article.');
    } finally {
      setLoading(false);
    }
  };

  const toggleStatus = async (targetStatus) => {
    if (!article || busy) return;
    setBusy(true);
    try {
      await api.patch(`/assets/knowledge-base/${id}/`, { status: targetStatus });
      setMsg(`${article.title} ${targetStatus}.`);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || `Could not ${targetStatus} article.`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); }, []);

  let statusActions;
  if (article && user) {
    const isStaff = user.role === 'system_admin' || user.role === 'it_manager' || user.role === 'it_support';
    if (isStaff) {
      if (article.status === 'draft') {
        statusActions = (
          <div className="row-end">
            <button type="button" className="btn-primary" onClick={() => toggleStatus('published')} disabled={busy}>
              Publish
            </button>
            <button type="button" className="btn-ghost" onClick={() => toggleStatus('archived')} disabled={busy}>
              Archive
            </button>
          </div>
        );
      } else if (article.status === 'published') {
        statusActions = (
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => toggleStatus('draft')} disabled={busy}>
              Set to draft
            </button>
            <button type="button" className="btn-ghost" onClick={() => toggleStatus('archived')} disabled={busy}>
              Archive
            </button>
          </div>
        );
      } else {
        statusActions = (
          <div className="row-end">
            <button type="button" className="btn-primary" onClick={() => toggleStatus('published')} disabled={busy}>
              Publish
            </button>
          </div>
        );
      }
    }
  }

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading article…
      </p>
    );
  }
  if (error) {
    return (
      <div className="form-wrap">
        <div className="error-summary" role="alert">{error}</div>
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
        sub={`Status: ${kbStatusLabel(article.status)}  •  Views: ${article.view_count ?? 0}  •  ${article.author_name ?? 'Unknown author'}`}
        actions={
          <div>
            <a className="btn-ghost" href="#/kb">← Back to knowledge base</a>
            {statusActions}
          </div>
        }
      />
      <div className="panel-pad">
        <div className="panel-section">
          <h4>Content</h4>
          <div className="kb-content" style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>{article.content || <span className="cell-muted">No content.</span>}</div>
        </div>
        <div className="panel-section">
          <h4>Details</h4>
          <div className="row-gap">
            <span><strong>Slug:</strong> {article.slug}</span>
            <span className="spacer" />
            <span><strong>Category:</strong> {article.category_name ?? 'None'}</span>
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
        {msg && <div className="success-summary" role="status">{msg}</div>}
      </div>
    </div>
  );

  function kbStatusLabel(s) {
    const m = { draft: 'Draft', published: 'Published', archived: 'Archived' };
    return m[s] ?? s;
  }
}

export default KnowledgeBase;
