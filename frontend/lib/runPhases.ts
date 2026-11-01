import type { RunStatus, Step } from "./types";

export type PhaseState = "todo" | "current" | "waiting" | "done" | "failed";

export type Phase = { id: string; label: string; state: PhaseState };

// The graph's twelve nodes, grouped into what a citizen would recognise.
const PHASES = [
  { id: "read", label: "Read the document", nodes: ["acquire", "parse", "segment"] },
  { id: "check", label: "Check each point", nodes: ["triage", "extract", "verify"] },
  { id: "you", label: "See if it applies to you", nodes: ["compile_rules", "evaluate"] },
  { id: "explain", label: "Explain it in your language", nodes: ["script", "translate", "guard", "tts"] },
];

function reachedPhase(steps: Step[]): number {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const found = PHASES.findIndex((p) => p.nodes.includes(steps[i].node));
    if (found >= 0) return found;
  }
  return -1;
}

export function runPhases(steps: Step[], status: RunStatus): Phase[] {
  const reached = reachedPhase(steps);
  return PHASES.map(({ id, label }, index) => {
    const at = (state: PhaseState) => ({ id, label, state });
    if (status === "completed") return at("done");
    if (status === "queued") return at("todo");
    if (index < reached) return at("done");
    if (status === "partial") return at(index === reached ? "done" : "todo");
    // A run that stopped before its first step stopped at the first phase.
    if (index !== Math.max(reached, 0)) return at("todo");
    if (status === "failed") return at("failed");
    return at(status === "waiting_input" ? "waiting" : "current");
  });
}
