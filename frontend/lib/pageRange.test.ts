import assert from "node:assert/strict";
import { test } from "node:test";

import { pageRangeProblem } from "./pageRange.ts";

test("a range inside the document and the limit is fine", () => {
  assert.equal(pageRangeProblem(1, 200, 300, 200), null);
  assert.equal(pageRangeProblem(300, 300, 300, 200), null);
});

test("a range outside the document is refused", () => {
  assert.match(pageRangeProblem(0, 5, 300, 200) ?? "", /between 1 and 300/);
  assert.match(pageRangeProblem(299, 301, 300, 200) ?? "", /between 1 and 300/);
});

test("a backwards range is refused", () => {
  assert.match(pageRangeProblem(9, 4, 300, 200) ?? "", /before/);
});

test("a range over the limit is refused", () => {
  assert.match(pageRangeProblem(1, 201, 300, 200) ?? "", /200 pages or fewer/);
});

test("an empty or fractional page number is refused", () => {
  assert.match(pageRangeProblem(Number.NaN, 5, 300, 200) ?? "", /whole/);
  assert.match(pageRangeProblem(1.5, 5, 300, 200) ?? "", /whole/);
});
