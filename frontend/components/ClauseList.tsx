import type { Clause } from "@/lib/types";

const KIND_STYLES: Record<Clause["kind"], string> = {
  heading: "font-semibold",
  para: "",
  table_row: "",
};

export function ClauseList({
  clauses,
  selectedId,
  pageFailed,
  onSelect,
}: {
  clauses: Clause[];
  selectedId?: string;
  pageFailed: boolean;
  onSelect: (clause: Clause) => void;
}) {
  if (pageFailed) {
    return (
      <p className="text-sm font-medium text-danger">
        We couldn&apos;t read this page, so nothing on it is used.
      </p>
    );
  }
  if (clauses.length === 0) {
    return <p className="text-sm text-muted">No text was found on this page.</p>;
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {clauses.map((clause) => {
        const selected = clause.id === selectedId;
        return (
          <li key={clause.id}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(clause)}
              className={`w-full rounded-md border px-3 py-2 text-left text-sm break-words focus-visible:outline-2 focus-visible:outline-accent ${
                selected
                  ? "border-highlight-strong bg-highlight-soft"
                  : "border-line bg-surface hover:border-accent"
              }`}
            >
              {clause.kind === "table_row" && (
                <span className="mb-0.5 block text-xs text-muted">
                  Table row
                </span>
              )}
              <span lang={clause.lang} className={KIND_STYLES[clause.kind]}>
                {clause.text}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
