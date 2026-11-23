import { memo } from 'react';

const EmptyStateInner = function EmptyState({ title, hint, action }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {hint ? <div className="small">{hint}</div> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
};

export const EmptyState = memo(EmptyStateInner);

const DataTableInner = function DataTable({ columns, rows, keyOf, selected, onToggle, emptyTitle, emptyHint, sort, onSort }) {
  if (!rows.length) return <EmptyState title={emptyTitle ?? 'Nothing here yet.'} hint={emptyHint} />;
  const selectable = typeof onToggle === 'function';
  const sortable = typeof onSort === 'function';
  const arrow = (field) => {
    if (!sort || sort.field !== field) return '';
    return sort.dir === 'desc' ? ' ▼' : ' ▲';
  };
  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            {selectable && <th className="th-select"><span className="visually-hidden">Select rows</span><span className="muted small" aria-hidden="true">✓</span></th>}
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.thClass}
                aria-sort={sort && sort.field === c.sortable ? (sort.dir === 'desc' ? 'descending' : 'ascending') : undefined}
              >
                {sortable && c.sortable ? (
                  <button
                    type="button" className="th-sort"
                    onClick={() => onSort(c.sortable)}
                    aria-label={`Sort by ${c.label}`}
                  >
                    {c.label}{arrow(c.sortable)}
                  </button>
                ) : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = keyOf(r);
            const isSel = selected?.has(k);
            return (
              <tr key={k} className={isSel ? 'selected' : ''}>
                {selectable && (
                  <td className="select-cell">
                    <input
                      type="checkbox" checked={!!isSel} onChange={() => onToggle(k)}
                      aria-label={`Select row ${k}`}
                    />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key}>{c.render ? c.render(r) : String(r[c.key] ?? '—')}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export const DataTable = memo(DataTableInner);

const PagerInner = function Pager({ count, hasNext, hasPrev, onPrev, onNext, busy, pageLabel }) {
  if (count == null && !hasNext && !hasPrev && !pageLabel) return null;
  return (
    <div className="pager">
      <span>{count != null ? <><span className="page-count">{count}</span> {count === 1 ? 'item' : 'items'}</> : ''}</span>
      {pageLabel ? <span className="muted">{pageLabel}</span> : null}
      <span className="spacer" />
      <button type="button" className="btn-small" onClick={onPrev} disabled={!hasPrev || busy}>&larr; Prev</button>
      <button type="button" className="btn-small" onClick={onNext} disabled={!hasNext || busy}>Next &rarr;</button>
    </div>
  );
};

export const Pager = memo(PagerInner);
