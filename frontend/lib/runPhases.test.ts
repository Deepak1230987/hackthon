import assert from "node:assert/strict";
import { test } from "node:test";

import { runPhases } from "./runPhases.ts";
import type { RunStatus, Step } from "./types";

const steps = (...nodes: string[]): Step[] =>
  nodes.map((node, id) => ({ id, node, attempt: 1, status: "done", events: [] }));

const states = (nodes: string[], status: RunStatus) =>
  runPhases(steps(...nodes), status).map((p) => p.state);

test("a queued run has started nothing", () => {
  assert.deepEqual(states([], "queued"), ["todo", "todo", "todo", "todo"]);
});

test("a running run marks the phase of its latest step", () => {
  assert.deepEqual(states(["acquire", "parse", "triage"], "running"), [
    "done",
    "current",
    "todo",
    "todo",
  ]);
});

test("a run with no steps yet is at the first phase", () => {
  assert.deepEqual(states([], "running"), ["current", "todo", "todo", "todo"]);
});

test("a correction loop stays in its phase", () => {
  assert.deepEqual(states(["extract", "verify", "extract"], "running"), [
    "done",
    "current",
    "todo",
    "todo",
  ]);
});

test("a question waits at the eligibility phase", () => {
  assert.deepEqual(states(["compile_rules", "evaluate"], "waiting_input"), [
    "done",
    "done",
    "waiting",
    "todo",
  ]);
});

test("a finished run is done everywhere, even if a phase was skipped", () => {
  assert.deepEqual(states(["acquire", "script"], "completed"), ["done", "done", "done", "done"]);
});

test("a partial run keeps what it reached and no more", () => {
  assert.deepEqual(states(["verify"], "partial"), ["done", "done", "todo", "todo"]);
});

test("a failed run marks where it stopped", () => {
  assert.deepEqual(states(["acquire", "extract"], "failed"), ["done", "failed", "todo", "todo"]);
  assert.deepEqual(states([], "failed"), ["failed", "todo", "todo", "todo"]);
});

test("an unknown node doesn't lose the phase", () => {
  assert.deepEqual(states(["acquire", "something_new"], "running"), [
    "current",
    "todo",
    "todo",
    "todo",
  ]);
});
