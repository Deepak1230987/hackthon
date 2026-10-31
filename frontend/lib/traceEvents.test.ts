import assert from "node:assert/strict";
import { test } from "node:test";

import { traceLines } from "./traceEvents.ts";
import type { RunEvent, RunEventType } from "./types.ts";

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

test("segment_done reports pages it couldn't read", () => {
  const lines = traceLines([
    event(1, "segment_done", { clauses: 9, failed_pages: [3, 5] }),
  ]);
  assert.equal(lines[1].text, "Couldn't read pages 3, 5");
  assert.equal(lines[1].tone, "bad");
  assert.notEqual(lines[0].key, lines[1].key);
});
