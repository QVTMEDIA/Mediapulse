import { useEffect, useState, type ReactNode } from 'react';

export const ROW_PAGE_SIZE = 20;

export function useLimitedRows<T>(rows: T[]) {
  const [visibleCount, setVisibleCount] = useState(ROW_PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(ROW_PAGE_SIZE);
  }, [rows.length]);

  return {
    visibleRows: rows.slice(0, visibleCount),
    hasMore: visibleCount < rows.length,
    canShowLess: visibleCount > ROW_PAGE_SIZE,
    showMore: () => setVisibleCount((current) => Math.min(current + ROW_PAGE_SIZE, rows.length)),
    showLess: () => setVisibleCount(ROW_PAGE_SIZE),
  };
}

export function LimitedRowsControls({
  shown,
  total,
  hasMore,
  canShowLess,
  onShowMore,
  onShowLess,
}: {
  shown: number;
  total: number;
  hasMore: boolean;
  canShowLess: boolean;
  onShowMore: () => void;
  onShowLess: () => void;
}) {
  if (!hasMore && !canShowLess) return null;
  return (
    <div className="row-limit-controls">
      <span>Showing {shown} of {total}</span>
      {hasMore && <button type="button" className="secondary-button" onClick={onShowMore}>Show more</button>}
      {canShowLess && <button type="button" className="secondary-button" onClick={onShowLess}>Show less</button>}
    </div>
  );
}

export function LimitedRows<T>({
  rows,
  render,
  empty,
}: {
  rows: T[];
  render: (row: T, index: number) => ReactNode;
  empty?: ReactNode;
}) {
  const limited = useLimitedRows(rows);
  return (
    <>
      {rows.length === 0 ? empty : limited.visibleRows.map(render)}
      <LimitedRowsControls
        shown={limited.visibleRows.length}
        total={rows.length}
        hasMore={limited.hasMore}
        canShowLess={limited.canShowLess}
        onShowMore={limited.showMore}
        onShowLess={limited.showLess}
      />
    </>
  );
}
