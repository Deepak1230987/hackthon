"use client";

import { useState } from "react";

import { correctionSummary, traceLines, type Tone } from "@/lib/traceEvents";
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
  running: { dot: "bg-accent animate-pulse motion-reduce:animate-none", label: "In progress" },
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
          {step.node === "extract" && step.attempt > 1
            ? "Correct rejected claims"
            : (NODE_LABELS[step.node] ?? step.node)}
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
          {traceLines(step.events, step.attempt).map(({ key, text, tone }) => (
            <li key={key} className={`break-words ${TONE_STYLES[tone]}`}>
              {text}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

const FOLD_ABOVE_STEPS = 3;

function SelfCheck({ steps, finished }: { steps: Step[]; finished: boolean }) {
  const { rejected, corrected, unresolved, unchecked } =
    correctionSummary(steps);
  if (rejected === 0 && unchecked === 0) return null;
  const count = (n: number) => `${n} ${n === 1 ? "claim" : "claims"}`;
  return (
    <div className="mb-4 flex flex-col gap-1 rounded-md border border-warning/30 bg-highlight-soft px-3 py-2 text-sm">
      {rejected > 0 && (
        <p>
          <span className="font-semibold">
            We caught {count(rejected)} that didn&apos;t match the document.
          </span>{" "}
          {corrected} corrected and passed.{" "}
          {unresolved > 0 &&
            (finished
              ? `${unresolved} left out, because we couldn't verify ${
                  unresolved === 1 ? "it" : "them"
                }.`
              : `${unresolved} still being checked.`)}
        </p>
      )}
      {unchecked > 0 && (
        <p>
          <span className="font-semibold">
            {count(unchecked)} couldn&apos;t be checked,
          </span>{" "}
          so {unchecked === 1 ? "it isn't" : "they aren't"} shown. Trying again
          later may find more.
        </p>
      )}
    </div>
  );
}

export function AgentTrace({
  steps,
  finished = false,
}: {
  steps: Step[];
  finished?: boolean;
}) {
  // A finished run's steps are long on a phone, so they fold away and leave the
  // self-check above them. While it runs they stay open to watch.
  const [choice, setChoice] = useState<boolean | null>(null);
  const foldable = finished && steps.length > FOLD_ABOVE_STEPS;
  const open = choice ?? !foldable;
  return (
    <section aria-labelledby="trace-heading">
      <h2 id="trace-heading" className="section-title mb-4">
        Steps
      </h2>
      <SelfCheck steps={steps} finished={finished} />
      {foldable && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setChoice(!open)}
          className="mb-3 min-h-11 rounded-md border border-line bg-surface px-3 text-sm font-medium hover:border-accent focus-visible:outline-2 focus-visible:outline-accent"
        >
          {open ? "Hide the steps" : `Show all ${steps.length} steps`}
        </button>
      )}
      {steps.length === 0 ? (
        <p className="text-muted">Waiting for the first step…</p>
      ) : (
        open && (
          <ol aria-live="polite" aria-relevant="additions">
            {steps.map((step) => (
              <StepRow key={step.id} step={step} />
            ))}
          </ol>
        )
      )}
    </section>
  );
}
