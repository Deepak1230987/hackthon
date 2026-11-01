import { Check, CircleAlert, Hand } from "lucide-react";

import { Spinner } from "@/components/ui";
import { runPhases, type PhaseState } from "@/lib/runPhases";
import type { RunStatus, Step } from "@/lib/types";

const DOT: Record<PhaseState, string> = {
  todo: "border border-line-strong bg-surface text-muted",
  current: "bg-accent text-white",
  waiting: "bg-highlight text-ink",
  done: "bg-success text-white",
  failed: "bg-danger text-white",
};

const STATE_TEXT: Record<PhaseState, string> = {
  todo: "Not started",
  current: "In progress",
  waiting: "Needs your answer",
  done: "Done",
  failed: "Stopped here",
};

function PhaseIcon({ state, number }: { state: PhaseState; number: number }) {
  if (state === "done") return <Check aria-hidden className="size-4" />;
  if (state === "failed") return <CircleAlert aria-hidden className="size-4" />;
  if (state === "waiting") return <Hand aria-hidden className="size-4" />;
  if (state === "current") return <Spinner className="size-4" />;
  return <span aria-hidden>{number}</span>;
}

// The whole run in four steps. The full list of checks is in the Document tab.
export function RunProgress({
  steps,
  status,
  compact = false,
}: {
  steps: Step[];
  status: RunStatus;
  compact?: boolean;
}) {
  const phases = runPhases(steps, status);
  const active = phases.find((p) => p.state === "current" || p.state === "waiting");

  if (compact) {
    return (
      <div>
        <p className="flex items-center justify-between gap-3 text-sm font-semibold">
          <span>{active?.label ?? "Waiting to start"}</span>
          <span className="shrink-0 font-normal text-muted">
            Step {Math.max(phases.findIndex((p) => p === active) + 1, 1)} of {phases.length}
          </span>
        </p>
        <ol className="mt-2 grid grid-cols-4 gap-1">
          {phases.map((phase) => (
            <li
              key={phase.id}
              aria-label={`${phase.label}: ${STATE_TEXT[phase.state]}`}
              className={`h-1.5 rounded-full ${
                phase.state === "done"
                  ? "bg-success"
                  : phase.state === "current"
                    ? "animate-pulse bg-accent motion-reduce:animate-none"
                    : phase.state === "waiting"
                      ? "bg-highlight-strong"
                      : phase.state === "failed"
                        ? "bg-danger"
                        : "bg-sunken"
              }`}
            />
          ))}
        </ol>
      </div>
    );
  }

  return (
    <ol className="flex flex-col gap-3">
      {phases.map((phase, index) => (
        <li key={phase.id} className="flex items-center gap-3">
          <span
            className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${DOT[phase.state]}`}
          >
            <PhaseIcon state={phase.state} number={index + 1} />
          </span>
          <span className={phase.state === "todo" ? "text-muted" : "font-semibold"}>
            {phase.label}
            <span className="sr-only">: {STATE_TEXT[phase.state]}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
