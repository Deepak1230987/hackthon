import { ChevronLeft, ChevronRight } from "lucide-react";

export function PagePicker({
  page,
  pageCount,
  onChange,
}: {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        aria-label="Previous page"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="btn btn-secondary btn-icon"
      >
        <ChevronLeft aria-hidden className="size-5" />
      </button>
      <label className="flex items-center gap-1.5 text-sm whitespace-nowrap text-muted">
        <span className="sr-only sm:not-sr-only">Page</span>
        <select
          value={page}
          aria-label="Page"
          onChange={(e) => onChange(Number(e.target.value))}
          className="min-h-11 rounded-xl border border-line-strong bg-surface px-2 text-base text-ink"
        >
          {Array.from({ length: pageCount }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {i + 1}
            </option>
          ))}
        </select>
        of {pageCount}
      </label>
      <button
        type="button"
        aria-label="Next page"
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
        className="btn btn-secondary btn-icon"
      >
        <ChevronRight aria-hidden className="size-5" />
      </button>
    </div>
  );
}
