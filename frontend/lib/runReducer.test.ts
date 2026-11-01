import assert from "node:assert/strict";
import { test } from "node:test";

import { initialRunState, runReducer, type RunState } from "./runReducer.ts";
import type {
  Claim,
  Question,
  RunEvent,
  RunEventType,
  RunStatus,
  Sentence,
} from "./types.ts";

const event = (
  seq: number,
  type: RunEventType,
  payload: Record<string, unknown> = {},
): RunEvent => ({ seq, type, payload });

const replay = (events: RunEvent[], state: RunState = initialRunState) =>
  events.reduce((s, e) => runReducer(s, { type: "event", event: e }), state);

const snapshot = (status: RunStatus, events: RunEvent[]) =>
  ({ type: "snapshot", run: { id: "r", status, events } }) as const;

test("builds steps from node events", () => {
  const { view } = replay([
    event(1, "run_status", { status: "running" }),
    event(2, "node_started", { node: "acquire" }),
    event(3, "fetch_attempt", { method: "upload" }),
    event(4, "node_finished", { node: "acquire", duration_ms: 12 }),
    event(5, "node_started", { node: "parse" }),
  ]);
  assert.equal(view.status, "running");
  assert.deepEqual(
    view.steps.map((s) => [s.node, s.status]),
    [
      ["acquire", "done"],
      ["parse", "running"],
    ],
  );
  assert.equal(view.steps[0].durationMs, 12);
  assert.equal(view.steps[0].events[0].type, "fetch_attempt");
});

test("records whether a finished node is really built", () => {
  const { view } = replay([
    event(1, "node_started", { node: "acquire" }),
    event(2, "node_finished", { node: "acquire", implemented: true }),
    event(3, "node_started", { node: "parse" }),
    event(4, "node_finished", { node: "parse", implemented: false }),
    event(5, "node_started", { node: "segment" }),
    event(6, "node_finished", { node: "segment" }),
  ]);
  assert.deepEqual(
    view.steps.map((s) => s.implemented),
    [true, false, true],
  );
});

test("ignores seq values already seen", () => {
  const events = [
    event(1, "node_started", { node: "acquire" }),
    event(2, "fetch_attempt", {}),
  ];
  const once = replay(events);
  const twice = replay(events, once);
  assert.equal(twice, once);
  assert.equal(twice.view.steps[0].events.length, 1);
});

test("a repeated node counts as a new attempt and stays visible", () => {
  const { view } = replay([
    event(1, "node_started", { node: "extract" }),
    event(2, "node_finished", { node: "extract" }),
    event(3, "node_started", { node: "verify" }),
    event(4, "claim_rejected", { reason: "QUOTE_NOT_IN_SOURCE" }),
    event(5, "node_finished", { node: "verify" }),
    event(6, "node_started", { node: "extract" }),
  ]);
  assert.deepEqual(
    view.steps.map((s) => [s.node, s.attempt]),
    [
      ["extract", 1],
      ["verify", 1],
      ["extract", 2],
    ],
  );
  assert.equal(view.steps[1].events[0].type, "claim_rejected");
});

test("a node cut off by a restart is marked interrupted", () => {
  const { view } = replay([
    event(1, "node_started", { node: "parse" }),
    event(2, "node_started", { node: "parse" }),
  ]);
  assert.deepEqual(
    view.steps.map((s) => s.status),
    ["interrupted", "running"],
  );
});

test("a failed run fails the running step and keeps the error", () => {
  const error = { code: "PDF_ENCRYPTED", message: "This file is locked." };
  const { view } = replay([
    event(1, "node_started", { node: "parse" }),
    event(2, "run_status", { status: "failed", error }),
  ]);
  assert.equal(view.status, "failed");
  assert.equal(view.steps[0].status, "failed");
  assert.deepEqual(view.error, error);
});

test("a refresh rebuilds the same view from a snapshot and a replay", () => {
  const events = [
    event(1, "run_status", { status: "running" }),
    event(2, "node_started", { node: "acquire" }),
    event(3, "node_finished", { node: "acquire" }),
  ];
  const fromStream = replay(events);
  const fromSnapshot = runReducer(
    initialRunState,
    snapshot("running", events.slice(0, 2)),
  );
  const resumed = replay(events, fromSnapshot);
  assert.equal(resumed.view.status, fromStream.view.status);
  assert.deepEqual(resumed.view.steps, fromStream.view.steps);
});

test("a stale snapshot does not move the status backwards", () => {
  const state = replay([
    event(1, "node_started", { node: "acquire" }),
    event(2, "run_status", { status: "completed" }),
  ]);
  const next = runReducer(
    state,
    snapshot("running", [event(1, "node_started", { node: "acquire" })]),
  );
  assert.equal(next.view.status, "completed");
});

test("clauses count as ready once segmentation is done", () => {
  const before = replay([event(1, "node_started", { node: "segment" })]);
  assert.equal(before.view.clausesReady, false);
  const after = replay([event(2, "segment_done", { clauses: 3 })], before);
  assert.equal(after.view.clausesReady, true);
});

test("a refresh after segmentation still knows clauses are ready", () => {
  const { view } = runReducer(
    initialRunState,
    snapshot("completed", [event(1, "segment_done", { clauses: 3 })]),
  );
  assert.equal(view.clausesReady, true);
});

const claim = (id: string): Claim => ({
  id,
  field: "benefit",
  text: `Claim ${id}`,
  quote: "a quote from the document",
  clauses: [],
});

test("verified claims arrive through snapshots", () => {
  const { view } = runReducer(initialRunState, {
    type: "snapshot",
    run: { id: "r", status: "running", claims: [claim("a")], events: [] },
  });
  assert.deepEqual(
    view.claims.map((c) => c.id),
    ["a"],
  );
});

test("an older snapshot can't remove a verified claim", () => {
  const newer = runReducer(initialRunState, {
    type: "snapshot",
    run: {
      id: "r",
      status: "running",
      claims: [claim("a"), claim("b")],
      events: [event(2, "claim_verified", { claim_id: "b" })],
    },
  });
  const { view } = runReducer(newer, {
    type: "snapshot",
    run: { id: "r", status: "running", claims: [claim("a")], events: [] },
  });
  assert.deepEqual(view.claims.map((c) => c.id).sort(), ["a", "b"]);
});

test("not stated comes from the latest snapshot only", () => {
  const latest = runReducer(initialRunState, {
    type: "snapshot",
    run: {
      id: "r",
      status: "completed",
      not_stated: ["penalty"],
      events: [event(3, "run_status", { status: "completed" })],
    },
  });
  const { view } = runReducer(latest, {
    type: "snapshot",
    run: {
      id: "r",
      status: "running",
      not_stated: ["penalty", "benefit"],
      events: [event(1, "node_started", { node: "extract" })],
    },
  });
  assert.deepEqual(view.notStated, ["penalty"]);
});

const sentence = (id: string, audio_path: string | null): Sentence => ({
  id,
  ordinal: 0,
  language: "hi",
  source_text: "English",
  translated_text: "हिन्दी",
  claim_ids: [],
  audio_path,
  guard_status: "passed",
});

test("an older snapshot can't take audio away", () => {
  const withAudio = runReducer(initialRunState, {
    type: "snapshot",
    run: { id: "r", status: "running", sentences: [sentence("a", "audio/a.mp3")], events: [] },
  });
  const { view } = runReducer(withAudio, {
    type: "snapshot",
    run: { id: "r", status: "running", sentences: [sentence("a", null)], events: [] },
  });
  assert.equal(view.sentences[0].audio_path, "audio/a.mp3");
});

test("an answered question goes away once the run moves on", () => {
  const question: Question = {
    name: "is_student",
    type: "bool",
    options: null,
    min: null,
    max: null,
    question_en: "Are you a student?",
    unit: null,
  };
  const waiting = runReducer(initialRunState, {
    type: "snapshot",
    run: { id: "r", status: "waiting_input", question, events: [] },
  });
  assert.equal(waiting.view.question?.name, "is_student");
  const { view } = replay([event(1, "run_status", { status: "running" })], waiting);
  assert.equal(view.question, undefined);
});

test("a terminal snapshot settles steps when polling missed the event", () => {
  const next = runReducer(
    initialRunState,
    snapshot("completed", [event(1, "node_started", { node: "tts" })]),
  );
  assert.equal(next.view.steps[0].status, "done");
});
