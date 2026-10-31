import assert from "node:assert/strict";
import { test } from "node:test";

import { correctionSummary, traceLines } from "./traceEvents.ts";
import type { RunEvent, RunEventType, Step } from "./types.ts";

function event(
  seq: number,
  type: RunEventType,
  payload: Record<string, unknown> = {},
): RunEvent {
  return { seq, type, payload };
}

test("OCR pages collapse into one line", () => {
  const lines = traceLines([
    event(1, "page_ocr", { page: 1, reason: "no_text" }),
    event(2, "page_ocr", { page: 2, reason: "no_text" }),
    event(3, "page_ocr", { page: 3, reason: "no_text" }),
  ]);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].text, "Read 3 pages with OCR");
  assert.equal(lines[0].tone, "plain");
});

test("a failed OCR page stays visible", () => {
  const [line] = traceLines([
    event(1, "page_ocr", { page: 4, reason: "no_text" }),
    event(2, "page_ocr", { page: 4, failed: true, reason: "recitation" }),
  ]);
  assert.equal(line.text, "Read 1 page with OCR. Couldn't read page 4");
  assert.equal(line.tone, "bad");
});

test("OCR keeps its place among other events", () => {
  const lines = traceLines([
    event(1, "fetch_attempt", { method: "http" }),
    event(2, "page_ocr", { page: 1 }),
    event(3, "segment_done", { clauses: 9, failed_pages: [] }),
    event(4, "page_ocr", { page: 2 }),
  ]);
  assert.deepEqual(
    lines.map((l) => l.text),
    [
      "Downloading from the site",
      "Read 2 pages with OCR",
      "Found 9 clauses",
    ],
  );
});

test("unfinished embedding is a warning, not a failure", () => {
  const [line] = traceLines([event(1, "embeddings_done", { embedded: false })]);
  assert.equal(line.tone, "warn");
});

test("segment_done reports pages it couldn't read", () => {
  const lines = traceLines([
    event(1, "segment_done", { clauses: 9, failed_pages: [3, 5] }),
  ]);
  assert.equal(lines[1].text, "Couldn't read pages 3, 5");
  assert.equal(lines[1].tone, "bad");
  assert.notEqual(lines[0].key, lines[1].key);
});

test("rejections are grouped by reason and stay visible", () => {
  const lines = traceLines([
    event(1, "claim_verified", { claim_id: "a" }),
    event(2, "claim_rejected", { claim_id: "b", reason: "QUOTE_NOT_IN_SOURCE" }),
    event(3, "retry", { reason: "QUOTE_NOT_IN_SOURCE" }),
    event(4, "claim_rejected", { claim_id: "c", reason: "QUOTE_NOT_IN_SOURCE" }),
    event(5, "retry", { reason: "QUOTE_NOT_IN_SOURCE" }),
    event(6, "claim_rejected", { claim_id: "d", reason: "NOT_ENTAILED" }),
  ]);
  assert.deepEqual(
    lines.map((l) => [l.text, l.tone]),
    [
      ["1 claim passed every check", "good"],
      ["Rejected 2 claims: the quote isn't in the cited clause", "bad"],
      ["Sent 2 claims back to be corrected", "warn"],
      ["Rejected 1 claim: the clause doesn't support it", "bad"],
    ],
  );
});

test("a provider failure reads as unchecked, not rejected", () => {
  const [line] = traceLines([
    event(1, "claim_rejected", { claim_id: "a", reason: "PROVIDERS_UNAVAILABLE" }),
  ]);
  assert.equal(line.text, "Couldn't check 1 claim: the AI provider couldn't check it");
  assert.equal(line.tone, "warn");
});

test("an unknown rejection reason is still shown", () => {
  const [line] = traceLines([
    event(1, "claim_rejected", { claim_id: "a", reason: "NEW_REASON" }),
  ]);
  assert.equal(line.text, "Rejected 1 claim: NEW_REASON");
});

test("extraction on a later attempt reads as a correction", () => {
  const events = [event(1, "claim_extracted", { claim_id: "a" })];
  assert.equal(traceLines(events)[0].text, "Extracted 1 claim");
  assert.equal(traceLines(events, 2)[0].text, "Rewrote 1 claim");
});

test("failover says what failed and what replaced it", () => {
  const [line] = traceLines([
    event(1, "failover", { from: "gemini", to: "openai", reason: "status 429" }),
  ]);
  assert.equal(line.text, "gemini failed (status 429), so we switched to openai");
  assert.equal(line.tone, "warn");
});

test("the summary follows a claim across attempts", () => {
  const step = (id: number, events: RunEvent[]): Step => ({
    id,
    node: "verify",
    attempt: 1,
    status: "done",
    events,
  });
  const summary = correctionSummary([
    step(1, [
      event(1, "claim_rejected", { claim_id: "a", attempt: 1 }),
      event(2, "claim_rejected", { claim_id: "b", attempt: 1 }),
      event(3, "claim_verified", { claim_id: "c" }),
    ]),
    step(4, [
      event(5, "claim_verified", { claim_id: "a" }),
      event(6, "claim_rejected", { claim_id: "b", attempt: 2 }),
    ]),
  ]);
  assert.deepEqual(summary, {
    rejected: 2,
    corrected: 1,
    unresolved: 1,
    unchecked: 0,
  });
});

test("a claim that couldn't be checked isn't called wrong", () => {
  const step: Step = {
    id: 1,
    node: "verify",
    attempt: 1,
    status: "done",
    events: [
      event(1, "claim_rejected", { claim_id: "a", reason: "PROVIDERS_UNAVAILABLE" }),
      event(2, "claim_rejected", { claim_id: "b", reason: "BUDGET_EXHAUSTED" }),
      event(3, "claim_rejected", { claim_id: "c", reason: "NOT_ENTAILED" }),
      event(4, "claim_rejected", { claim_id: "c", reason: "PROVIDERS_UNAVAILABLE" }),
    ],
  };
  assert.deepEqual(correctionSummary([step]), {
    rejected: 1,
    corrected: 0,
    unresolved: 0,
    unchecked: 3,
  });
});
