import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';

export const ROW_PAGE_SIZE = 20;

export function useLimitedRows<T>(rows: T[]) {
  const [page, setPage] = useState(1);

  useEffect(() => {
    setPage(1);
  }, [rows.length]);

  const pageCount = Math.max(1, Math.ceil(rows.length / ROW_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);

  return {
    visibleRows: rows.slice((currentPage - 1) * ROW_PAGE_SIZE, currentPage * ROW_PAGE_SIZE),
    page: currentPage,
    pageCount,
    goToPage: setPage,
  };
}

export function LimitedRowsControls({
  visibleRows,
  total,
  page,
  pageCount,
  goToPage,
}: {
  visibleRows: unknown[];
  total: number;
  page: number;
  pageCount: number;
  goToPage: (page: number) => void;
}) {
  if (pageCount <= 1) return null;
  const start = (page - 1) * ROW_PAGE_SIZE + 1;
  const end = Math.min(page * ROW_PAGE_SIZE, total);
  const pageItems: Array<number | 'ellipsis'> = [];
  if (pageCount <= 7) {
    for (let value = 1; value <= pageCount; value += 1) pageItems.push(value);
  } else {
    pageItems.push(1);
    if (page > 4) pageItems.push('ellipsis');
    for (let value = Math.max(2, page - 1); value <= Math.min(pageCount - 1, page + 1); value += 1) pageItems.push(value);
    if (page < pageCount - 3) pageItems.push('ellipsis');
    pageItems.push(pageCount);
  }
  return (
    <div className="row-limit-controls">
      <span>Showing {start}-{end} of {total}</span>
      <div className="row-pagination" aria-label="Row pages">
        <button type="button" className="page-button" aria-label="Previous page" disabled={page === 1} onClick={() => goToPage(page - 1)}>
          <ChevronLeft size={16} aria-hidden />
        </button>
        {pageItems.map((item, index) => item === 'ellipsis' ? (
          <span className="page-ellipsis" key={`ellipsis-${index}`}>...</span>
        ) : (
          <button type="button" className={`page-button${item === page ? ' page-button-active' : ''}`} aria-current={item === page ? 'page' : undefined} onClick={() => goToPage(item)} key={item}>
            {item}
          </button>
        ))}
        <button type="button" className="page-button" aria-label="Next page" disabled={page === pageCount} onClick={() => goToPage(page + 1)}>
          <ChevronRight size={16} aria-hidden />
        </button>
      </div>
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
      <LimitedRowsControls {...limited} total={rows.length} />
    </>
  );
}
