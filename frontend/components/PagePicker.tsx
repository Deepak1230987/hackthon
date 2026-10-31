const BUTTON =
  "min-h-11 min-w-11 rounded-md border border-line bg-surface px-3 font-medium hover:border-accent disabled:cursor-not-allowed disabled:text-line disabled:hover:border-line focus-visible:outline-2 focus-visible:outline-accent";

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
    <div className="flex items-center gap-2">
      <button
        type="button"
        aria-label="Previous page"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className={BUTTON}
      >
        ‹
      </button>
      <label className="flex items-center gap-2 text-sm text-muted">
        Page
        <select
          value={page}
          onChange={(e) => onChange(Number(e.target.value))}
          className="min-h-11 rounded-md border border-line bg-surface px-2 text-ink focus-visible:outline-2 focus-visible:outline-accent"
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
        className={BUTTON}
      >
        ›
      </button>
    </div>
  );
}
