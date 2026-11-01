import { Notice } from "@/components/ui";
import type { Clause } from "@/lib/types";

const KIND_STYLES: Record<Clause["kind"], string> = {
  heading: "text-lg font-semibold",
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
      <Notice tone="danger">
        We couldn&apos;t read this page, so nothing on it is used.
      </Notice>
    );
  }
  if (clauses.length === 0) {
    return <p className="text-sm text-muted">No text was found on this page.</p>;
  }
  return (
    <ul className="flex flex-col gap-1">
      {clauses.map((clause) => {
        const selected = clause.id === selectedId;
        return (
          <li key={clause.id}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(clause)}
              className={`w-full rounded-lg px-3 py-2 text-left font-display leading-relaxed break-words transition-colors ${
                selected
                  ? "bg-highlight-soft shadow-[inset_3px_0_0_var(--color-highlight-strong)]"
                  : "hover:bg-sunken/70"
              }`}
            >
              {clause.kind === "table_row" && (
                <span className="mb-0.5 block font-sans text-xs text-muted">
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
