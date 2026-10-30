import assert from "node:assert/strict";
import { test } from "node:test";

import { initialRunState, runReducer, type RunState } from "./runReducer.ts";
import type { RunEvent, RunEventType, RunStatus } from "./types.ts";

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

test("a terminal snapshot settles steps when polling missed the event", () => {
  const next = runReducer(
    initialRunState,
    snapshot("completed", [event(1, "node_started", { node: "tts" })]),
  );
  assert.equal(next.view.steps[0].status, "done");
});
