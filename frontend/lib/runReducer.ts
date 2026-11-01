import type {
  ApiError,
  Claim,
  RunEvent,
  RunSnapshot,
  RunStatus,
  RunView,
  Sentence,
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
  view: {
    status: "queued",
    clausesReady: false,
    claims: [],
    notStated: [],
    sentences: [],
    steps: [],
  },
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

// A verified claim stays verified, so an older snapshot can only be missing some.
function mergeClaims(known: Claim[], incoming: Claim[]): Claim[] {
  const ids = new Set(incoming.map((c) => c.id));
  return [...incoming, ...known.filter((c) => !ids.has(c.id))];
}

// Audio only ever gets added, so an older snapshot can't take it away.
function mergeSentences(known: Sentence[], incoming: Sentence[]): Sentence[] {
  if (incoming.length === 0) return known;
  const audio = new Map(known.map((s) => [s.id, s.audio_path]));
  return incoming.map((s) => ({
    ...s,
    audio_path: s.audio_path ?? audio.get(s.id) ?? null,
  }));
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
    if (view.status !== "waiting_input") view.question = undefined;
  }
  if (event.type === "segment_done") view.clausesReady = true;
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
        language: action.run.language ?? next.view.language,
        document: action.run.document ?? next.view.document,
        claims: mergeClaims(next.view.claims, action.run.claims ?? []),
        verdict: action.run.verdict ?? next.view.verdict,
        sentences: mergeSentences(next.view.sentences, action.run.sentences ?? []),
      };
      // A snapshot requested before newer stream events arrived must not move
      // the status backwards.
      const latest = Math.max(-1, ...action.run.events.map((e) => e.seq));
      if (latest >= state.maxSeq) {
        view.status = action.run.status;
        view.error = action.run.error ?? view.error;
        view.notStated = action.run.not_stated ?? view.notStated;
        view.question = action.run.question ?? undefined;
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
