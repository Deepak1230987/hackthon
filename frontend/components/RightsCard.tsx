import { isTerminal } from "@/lib/runReducer";
import type { Claim, ClaimField, ClauseRef, RunStatus } from "@/lib/types";

const FIELDS: { field: ClaimField; label: string }[] = [
  { field: "benefit", label: "What you can get" },
  { field: "eligibility", label: "Who is eligible" },
  { field: "document", label: "Documents needed" },
  { field: "deadline", label: "Deadlines" },
  { field: "authority", label: "Who handles this" },
  { field: "obligation", label: "What you must do" },
  { field: "penalty", label: "Penalties" },
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
      className={`rounded-md border ${
        selected
          ? "border-highlight-strong bg-highlight-soft"
          : "border-line bg-surface hover:border-accent"
      }`}
    >
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onShowSource(first)}
        className="w-full rounded-md px-3 py-2 text-left break-words focus-visible:outline-2 focus-visible:outline-accent"
      >
        <span className="block">{claim.text}</span>
        <span
          lang={DEVANAGARI.test(claim.quote) ? "hi" : undefined}
          className="mt-1 block border-l-2 border-line pl-2 text-sm text-muted"
        >
          {claim.quote}
        </span>
        <span className="mt-1 block text-sm font-medium text-accent">
          See the source on page {first.page}
        </span>
      </button>
      {others.length > 0 && (
        <div className="flex flex-wrap gap-x-4 px-3 pb-2 text-sm">
          {others.map((source) => (
            <button
              key={source.id}
              type="button"
              onClick={() => onShowSource(source)}
              className="min-h-11 font-medium text-accent underline focus-visible:outline-2 focus-visible:outline-accent"
            >
              Also on page {source.page}
            </button>
          ))}
        </div>
      )}
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
      <h2 id="rights-heading" className="text-lg font-semibold">
        Your rights in this document
      </h2>
      <p className="mt-1 text-sm text-muted">
        Each point was checked against the clause it came from. Tap one to see
        it in the document.
      </p>

      {!finished && usable.length === 0 && (
        <p role="status" className="mt-3 text-sm text-muted">
          Points appear here as they pass the checks.
        </p>
      )}

      <div aria-live="polite" className="mt-3 flex flex-col gap-4">
        {FIELDS.map(({ field, label }) => {
          const group = usable.filter((c) => c.field === field);
          if (group.length === 0) return null;
          return (
            <div key={field}>
              <h3 className="mb-1.5 font-semibold">{label}</h3>
              <ul className="flex flex-col gap-1.5">
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

      {finished && missing.length > 0 && (
        <div className="mt-4 rounded-md border border-line bg-surface px-3 py-2 text-sm">
          <h3 className="font-semibold">
            {status === "completed"
              ? "We didn't find these in this document"
              : "Not confirmed in this run"}
          </h3>
          <p className="mt-0.5 text-muted">
            {missing.map((f) => f.label).join(" · ")}
          </p>
          <p className="mt-1 text-muted">
            {status === "completed"
              ? "This check can miss things, so the document may still cover them. Look through the clauses below, or ask the issuing office."
              : "This run ended early, so the document may still cover these."}
          </p>
        </div>
      )}
    </section>
  );
}
