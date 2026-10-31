import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDate, isOldDocument, sourceHost } from "./provenance.ts";

const NOW = new Date("2026-10-31T00:00:00Z");

test("a document past the age limit is old", () => {
  assert.equal(isOldDocument("2021-10-30", NOW), true);
  assert.equal(isOldDocument("2021-11-01", NOW), false);
});

test("an unknown issue date isn't called old", () => {
  assert.equal(isOldDocument(null, NOW), false);
  assert.equal(isOldDocument(undefined, NOW), false);
});

test("an issue date doesn't shift with the time zone", () => {
  assert.equal(formatDate("2024-01-01"), "1 Jan 2024");
});

test("only web links count as a source", () => {
  assert.equal(sourceHost("https://pmkisan.gov.in/a.pdf"), "pmkisan.gov.in");
  assert.equal(sourceHost("javascript:alert(1)"), null);
  assert.equal(sourceHost("not a link"), null);
  assert.equal(sourceHost(null), null);
});
