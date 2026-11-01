import {
  CalendarClock,
  ClipboardCheck,
  FileText,
  Gift,
  Landmark,
  ListChecks,
  SearchX,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { SourceChip } from "@/components/ui";
import { isTerminal } from "@/lib/runReducer";
import type { Claim, ClaimField, ClauseRef, RunStatus } from "@/lib/types";

const FIELDS: { field: ClaimField; label: string; icon: LucideIcon }[] = [
  { field: "benefit", label: "What you can get", icon: Gift },
  { field: "eligibility", label: "Who is eligible", icon: ClipboardCheck },
  { field: "document", label: "Documents needed", icon: FileText },
  { field: "deadline", label: "Deadlines", icon: CalendarClock },
  { field: "authority", label: "Who handles this", icon: Landmark },
  { field: "obligation", label: "What you must do", icon: ListChecks },
  { field: "penalty", label: "Penalties", icon: TriangleAlert },
];

const DEVANAGARI = /[ऀ-ॿ]/;

function ClaimRow({
  claim,
  selectedClauseId,
  onShowSource,
}: {
  claim: Claim;
  selectedClauseId?: string;
  onShowSource: (source: ClauseRef) => void;
}) {
  const [first, ...others] = claim.clauses;
  const selected = claim.clauses.some((c) => c.id === selectedClauseId);
  return (
    <li
      className={`transition-colors ${
        selected
          ? "bg-highlight-soft shadow-[inset_4px_0_0_var(--color-highlight-strong)]"
          : ""
      }`}
    >
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onShowSource(first)}
        className="group w-full px-4 pt-3 text-left break-words"
      >
        <span className="block text-lg leading-snug font-medium">{claim.text}</span>
        <span
          lang={DEVANAGARI.test(claim.quote) ? "hi" : undefined}
          className="mt-1 block font-display leading-relaxed text-muted"
        >
          “{claim.quote}”
        </span>
      </button>
      <div className="flex flex-wrap gap-x-2 px-4 pb-1">
        <SourceChip page={first.page} onClick={() => onShowSource(first)} />
        {others.map((source) => (
          <SourceChip
            key={source.id}
            page={source.page}
            label={`Also on page ${source.page}`}
            onClick={() => onShowSource(source)}
          />
        ))}
      </div>
    </li>
  );
}

export function RightsCard({
  status,
  claims,
  notStated,
  selectedClauseId,
  onShowSource,
}: {
  status: RunStatus;
  claims: Claim[];
  notStated: ClaimField[];
  selectedClauseId?: string;
  onShowSource: (source: ClauseRef) => void;
}) {
  const finished = isTerminal(status);
  if (status === "failed" && claims.length === 0) return null;

  const usable = claims.filter((c) => c.clauses.length > 0);
  const missing = FIELDS.filter((f) => notStated.includes(f.field));

  return (
    <section aria-labelledby="rights-heading">
      <h2 id="rights-heading" className="section-title">
        Your rights in this document
      </h2>
      <p className="mt-1 flex gap-2 text-sm text-muted">
        <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
        Each point was checked against the clause it came from. Tap one to see
        it in the document.
      </p>

      {!finished && usable.length === 0 && (
        <p role="status" className="mt-3 text-sm text-muted">
          Points appear here as they pass the checks.
        </p>
      )}

      <div aria-live="polite" className="mt-4 flex flex-col gap-4 empty:hidden">
        {FIELDS.map(({ field, label, icon: Icon }) => {
          const group = usable.filter((c) => c.field === field);
          if (group.length === 0) return null;
          return (
            <div key={field} className="card overflow-hidden">
              <h3 className="flex items-center gap-2.5 border-b border-line bg-sunken/40 px-4 py-2.5 font-semibold">
                <Icon aria-hidden className="size-5 text-accent" />
                {label}
                <span className="ml-auto text-sm font-normal text-muted">{group.length}</span>
              </h3>
              <ul className="divide-y divide-line">
                {group.map((claim) => (
                  <ClaimRow
                    key={claim.id}
                    claim={claim}
                    selectedClauseId={selectedClauseId}
                    onShowSource={onShowSource}
                  />
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      {finished && usable.length === 0 && (
        <p className="mt-3 text-sm text-muted">
          We couldn&apos;t confirm any rights from this document. You can still
          read its clauses in the Document tab.
        </p>
      )}

      {finished && missing.length > 0 && (
        <div className="mt-4 flex gap-3 rounded-2xl border border-dashed border-line-strong px-4 py-3 text-sm">
          <SearchX aria-hidden className="mt-0.5 size-5 shrink-0 text-muted" />
          <div>
            <h3 className="font-semibold">
              {status === "completed"
                ? "We didn't find these in this document"
                : "Not confirmed in this run"}
            </h3>
            <p className="mt-0.5 font-medium">
              {missing.map((f) => f.label).join(" · ")}
            </p>
            <p className="mt-1 text-muted">
              {status === "completed"
                ? "This check can miss things, so the document may still cover them. Look through its clauses in the Document tab, or ask the issuing office."
                : "This run ended early, so the document may still cover these."}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
