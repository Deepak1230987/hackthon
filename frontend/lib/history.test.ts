import assert from "node:assert/strict";
import { test } from "node:test";

import {
  parseHistory,
  withEntry,
  withoutEntry,
  type HistoryEntry,
} from "./history.ts";

function entry(runId: string, overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  return {
    runId,
    title: `Document ${runId}`,
    status: "completed",
    openedAt: "2026-11-01T00:00:00.000Z",
    ...overrides,
  };
}

test("the newest run comes first", () => {
  const entries = withEntry([entry("a")], entry("b"));
  assert.deepEqual(entries.map((e) => e.runId), ["b", "a"]);
});

test("a run seen again updates in place and keeps its first date", () => {
  const first = [entry("a"), entry("b", { status: "running", title: null })];
  const entries = withEntry(
    first,
    entry("b", { title: "Named", openedAt: "2026-12-01T00:00:00.000Z" }),
  );
  assert.deepEqual(entries.map((e) => e.runId), ["a", "b"]);
  assert.equal(entries[1].title, "Named");
  assert.equal(entries[1].status, "completed");
  assert.equal(entries[1].openedAt, "2026-11-01T00:00:00.000Z");
});

test("the oldest run drops off once the list is full", () => {
  let entries: HistoryEntry[] = [];
  for (let i = 0; i < 25; i++) entries = withEntry(entries, entry(String(i)));
  assert.equal(entries.length, 20);
  assert.equal(entries[0].runId, "24");
  assert.equal(entries[19].runId, "5");
});

test("a removed run is gone and the rest stay", () => {
  const entries = withoutEntry([entry("a"), entry("b")], "a");
  assert.deepEqual(entries.map((e) => e.runId), ["b"]);
});

test("unreadable storage gives an empty list", () => {
  assert.deepEqual(parseHistory(null), []);
  assert.deepEqual(parseHistory("not json"), []);
  assert.deepEqual(parseHistory('{"runId":"a"}'), []);
});

test("malformed entries are dropped and good ones kept", () => {
  const raw = JSON.stringify([entry("a"), { runId: 1 }, null, entry("b", { title: null })]);
  assert.deepEqual(parseHistory(raw).map((e) => e.runId), ["a", "b"]);
});
