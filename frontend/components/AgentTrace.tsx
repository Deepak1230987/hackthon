import { traceLines, type Tone } from "@/lib/traceEvents";
import type { Step, StepStatus } from "@/lib/types";

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

const NOT_BUILT_STYLE = { dot: "bg-line", label: "Not built yet" };

const TONE_STYLES: Record<Tone, string> = {
  plain: "text-muted",
  good: "text-success",
  warn: "text-warning font-medium",
  bad: "text-danger font-medium",
};

function formatDuration(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function StepRow({ step }: { step: Step }) {
  const notBuilt = step.implemented === false;
  const status = notBuilt ? NOT_BUILT_STYLE : STATUS_STYLES[step.status];
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
          {!notBuilt &&
            step.durationMs !== undefined &&
            ` · ${formatDuration(step.durationMs)}`}
        </span>
      </div>
      {step.events.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-sm">
          {traceLines(step.events).map(({ key, text, tone }) => (
            <li key={key} className={`break-words ${TONE_STYLES[tone]}`}>
              {text}
            </li>
          ))}
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
