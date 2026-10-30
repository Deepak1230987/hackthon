import type {
  ApiError,
  RunEvent,
  RunSnapshot,
  RunStatus,
  RunView,
  Step,
  StepStatus,
} from "./types";

export type RunState = {
  view: RunView;
  seen: ReadonlySet<number>;
  maxSeq: number;
};

export type RunAction =
  | { type: "event"; event: RunEvent }
  | { type: "snapshot"; run: RunSnapshot }
  | { type: "rejected"; error: ApiError };

export const initialRunState: RunState = {
  view: { status: "queued", steps: [] },
  seen: new Set(),
  maxSeq: -1,
};

export function isTerminal(status: RunStatus): boolean {
  return status === "completed" || status === "partial" || status === "failed";
}

function settleRunning(steps: Step[], status: StepStatus): Step[] {
  return steps.map((s) => (s.status === "running" ? { ...s, status } : s));
}

function replaceLast(steps: Step[], index: number, step: Step): Step[] {
  return steps.map((s, i) => (i === index ? step : s));
}

function applyToSteps(steps: Step[], event: RunEvent): Step[] {
  const node = String(event.payload.node ?? "");

  if (event.type === "node_started") {
    // The graph runs one node at a time, so a step still running here was cut
    // off, for example by a backend restart.
    const settled = settleRunning(steps, "interrupted");
    const attempt = steps.filter((s) => s.node === node).length + 1;
    return [
      ...settled,
      { id: event.seq, node, attempt, status: "running", events: [] },
    ];
  }

  if (event.type === "node_finished") {
    const index = steps.findLastIndex(
      (s) => s.node === node && s.status === "running",
    );
    if (index < 0) return steps;
    const durationMs =
      typeof event.payload.duration_ms === "number"
        ? event.payload.duration_ms
        : undefined;
    return replaceLast(steps, index, {
      ...steps[index],
      status: "done",
      durationMs,
      implemented: event.payload.implemented !== false,
    });
  }

  if (event.type === "run_status") {
    const status = event.payload.status as RunStatus;
    if (status === "failed") return settleRunning(steps, "failed");
    if (isTerminal(status)) return settleRunning(steps, "done");
    return steps;
  }

  // Detail events belong to whichever step is current.
  const last = steps.length - 1;
  if (last < 0) {
    return [
      {
        id: event.seq,
        node: node || "run",
        attempt: 1,
        status: "running",
        events: [event],
      },
    ];
  }
  return replaceLast(steps, last, {
    ...steps[last],
    events: [...steps[last].events, event],
  });
}

function applyEvent(state: RunState, event: RunEvent): RunState {
  if (state.seen.has(event.seq)) return state;

  const seen = new Set(state.seen).add(event.seq);
  const view: RunView = {
    ...state.view,
    steps: applyToSteps(state.view.steps, event),
  };
  if (event.type === "run_status") {
    view.status = event.payload.status as RunStatus;
    if (event.payload.error) view.error = event.payload.error as ApiError;
  }
  return { view, seen, maxSeq: Math.max(state.maxSeq, event.seq) };
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "event":
      return applyEvent(state, action.event);

    case "snapshot": {
      const next = action.run.events.reduce(applyEvent, state);
      const view = {
        ...next.view,
        document: action.run.document ?? next.view.document,
      };
      // A snapshot requested before newer stream events arrived must not move
      // the status backwards.
      const latest = Math.max(-1, ...action.run.events.map((e) => e.seq));
      if (latest >= state.maxSeq) {
        view.status = action.run.status;
        view.error = action.run.error ?? view.error;
        if (action.run.status === "failed") {
          view.steps = settleRunning(view.steps, "failed");
        } else if (isTerminal(action.run.status)) {
          view.steps = settleRunning(view.steps, "done");
        }
      }
      return { ...next, view };
    }

    case "rejected":
      return {
        ...state,
        view: { ...state.view, status: "failed", error: action.error },
      };
  }
}
