/** Standardized loading primitives.
 *
 * Skeleton: animated placeholder for text/lines while content loads.
 * PageLoading: full-page loading indicator used between route changes.
 * ListSkeleton: rows of skeletons for table/list loading.
 */

import { memo, useMemo } from 'react';
import { EmptyState } from '../../components';

/** Single animated line skeleton. */
const SkeletonLine = memo(({ width = '100%', className = '' }) => (
  <span
    className={`skeleton-line ${className}`}
    style={{ width }}
    aria-hidden="true"
  />
));

/** Text skeleton: renders N lines of placeholder text. */
export const Skeleton = memo(({ lines = 3, width = '100%', className = '' }) => {
  const lineEls = useMemo(
    () => Array.from({ length: lines }, (_, i) => (
      <span key={i} className="skeleton-lines">
        <SkeletonLine width={i === lines - 1 ? '60%' : width} />
      </span>
    )),
    [lines, width]
  );
  return (
    <div className={`skeleton ${className}`} aria-label="Loading" role="status">
      {lineEls}
    </div>
  );
});

/** List/table skeleton: renders N row skeletons. */
export const ListSkeleton = memo(({ rows = 5, className = '' }) => {
  const rowEls = useMemo(
    () => Array.from({ length: rows }, (_, i) => (
      <div key={i} className="skeleton-row">
        <SkeletonLine width="10%" />
        <SkeletonLine width="40%" />
        <SkeletonLine width="35%" />
        <SkeletonLine width="20%" />
        <SkeletonLine width="25%" />
      </div>
    )),
    [rows]
  );
  return (
    <div className={`skeleton-list ${className}`} aria-label="Loading list" role="status">
      {rowEls}
    </div>
  );
});

/** Full-page loading indicator used between route changes. */
export const PageLoading = memo(({ message = 'Loading page…' }) => (
  <p className="page-loading" role="status">
    <span className="spinner" aria-hidden="true" />
    {message}
  </p>
));

/** Page-level empty state wrapper with a primary action. */
export const PageEmpty = memo(({ title, hint, action }) => (
    <div className="panel panel-pad">
      <EmptyState title={title} hint={hint} action={action} />
    </div>
  ));

