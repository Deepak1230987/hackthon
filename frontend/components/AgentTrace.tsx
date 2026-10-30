import type { RunEvent, Step, StepStatus } from "@/lib/types";

const NODE_LABELS: Record<string, string> = {
  acquire: "Get the document",
  parse: "Read the pages",
  segment: "Split into clauses",
  triage: "Check it is a policy",
  extract: "Extract rights",
  verify: "Verify against the source",
  compile_rules: "Build eligibility rules",
  evaluate: "Check eligibility",
  script: "Write the explanation",
  translate: "Translate",
  guard: "Check numbers and meaning",
  tts: "Generate speech",
};

const STATUS_STYLES: Record<StepStatus, { dot: string; label: string }> = {
  running: { dot: "bg-accent animate-pulse", label: "In progress" },
  done: { dot: "bg-success", label: "Done" },
  failed: { dot: "bg-danger", label: "Failed" },
  interrupted: { dot: "bg-warning", label: "Interrupted" },
};

type Tone = "plain" | "good" | "warn" | "bad";

const TONE_STYLES: Record<Tone, string> = {
  plain: "text-muted",
  good: "text-success",
  warn: "text-warning font-medium",
  bad: "text-danger font-medium",
};

function describe(event: RunEvent): { text: string; tone: Tone } {
  const p = event.payload;
  const suffix = (value: unknown) => (value ? `: ${String(value)}` : "");
  switch (event.type) {
    case "fetch_attempt":
      return { text: `Fetch attempt${suffix(p.method)}`, tone: "plain" };
    case "page_ocr":
      return { text: `OCR on page ${p.page ?? "?"}`, tone: "plain" };
    case "segment_done":
      return { text: `Found ${p.clauses ?? "?"} clauses`, tone: "plain" };
    case "triage_result":
      return {
        text: p.is_policy ? "This is a policy document" : "Not a policy document",
        tone: p.is_policy ? "good" : "warn",
      };
    case "claim_extracted":
      return { text: `Claim extracted${suffix(p.field)}`, tone: "plain" };
    case "claim_verified":
      return { text: "Claim verified", tone: "good" };
    case "claim_rejected":
      return { text: `Claim rejected${suffix(p.reason)}`, tone: "bad" };
    case "retry":
      return { text: `Retrying${suffix(p.reason)}`, tone: "warn" };
    case "rules_compiled":
      return { text: `Compiled ${p.count ?? "?"} rules`, tone: "plain" };
    case "needs_input":
      return { text: "Waiting for your answer", tone: "warn" };
    case "verdict":
      return { text: `Result${suffix(p.outcome)}`, tone: "plain" };
    case "script_ready":
      return { text: `Script has ${p.sentences ?? "?"} sentences`, tone: "plain" };
    case "sentence_translated":
      return { text: `Sentence translated${suffix(p.translator)}`, tone: "plain" };
    case "failover":
      return {
        text: `Switched provider${p.to ? ` to ${String(p.to)}` : ""}`,
        tone: "warn",
      };
    case "guard_failed":
      return { text: `Guard failed${suffix(p.reason)}`, tone: "bad" };
    case "sentence_ready":
      return { text: "Sentence audio ready", tone: "good" };
    default:
      return { text: event.type, tone: "plain" };
  }
}

function formatDuration(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function StepRow({ step }: { step: Step }) {
  const status = STATUS_STYLES[step.status];
  return (
    <li className="relative pb-5 pl-6 last:pb-0">
      <span
        aria-hidden
        className="absolute top-[7px] bottom-[-7px] left-[5px] w-px bg-line [li:last-child>&]:hidden"
      />
      <span
        aria-hidden
        className={`absolute top-[7px] left-0 size-[11px] rounded-full ${status.dot}`}
      />
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="font-medium">
          {NODE_LABELS[step.node] ?? step.node}
          {step.attempt > 1 && (
            <span className="font-normal text-muted">
              {" "}
              · attempt {step.attempt}
            </span>
          )}
        </span>
        <span className="text-sm text-muted">
          {status.label}
          {step.durationMs !== undefined &&
            ` · ${formatDuration(step.durationMs)}`}
        </span>
      </div>
      {step.events.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-sm">
          {step.events.map((event) => {
            const { text, tone } = describe(event);
            return (
              <li key={event.seq} className={`break-words ${TONE_STYLES[tone]}`}>
                {text}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

export function AgentTrace({ steps }: { steps: Step[] }) {
  return (
    <section aria-labelledby="trace-heading">
      <h2 id="trace-heading" className="mb-4 text-lg font-semibold">
        Steps
      </h2>
      {steps.length === 0 ? (
        <p className="text-muted">Waiting for the first step…</p>
      ) : (
        <ol aria-live="polite" aria-relevant="additions">
          {steps.map((step) => (
            <StepRow key={step.id} step={step} />
          ))}
        </ol>
      )}
    </section>
  );
}
