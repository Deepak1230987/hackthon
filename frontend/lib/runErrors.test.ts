import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { errorStep, KNOWN_ERROR_CODES } from "./runErrors.ts";

function pythonFiles(folder: string): string[] {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) return pythonFiles(path);
    return name.endsWith(".py") ? [path] : [];
  });
}

test("every code that can end a run has a screen", () => {
  const source = pythonFiles("../backend/app")
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  const runFailed = [...source.matchAll(/RunFailed\(\s*(?:f?")([A-Z_]+)"/g)].map((m) => m[1]);
  const failures = [...source.matchAll(/_fail\(\s*run_id,\s*"([A-Z_]+)"/g)].map((m) => m[1]);
  assert.ok(runFailed.length > 3, "the search found the backend's codes");
  for (const code of new Set([...runFailed, ...failures])) {
    assert.ok(KNOWN_ERROR_CODES.includes(code), `${code} has no screen`);
  }
});

test("an error a retry can fix offers one, and others offer another document", () => {
  assert.equal(errorStep({ code: "PROVIDERS_UNAVAILABLE", message: "" }).next, "retry");
  assert.equal(errorStep({ code: "PDF_ENCRYPTED", message: "" }).next, "another");
  assert.equal(errorStep({ code: "MULTIPLE_PDFS", message: "" }).next, "choose");
});

test("an unknown code still gives a way forward", () => {
  assert.deepEqual(errorStep({ code: "NEW_CODE", message: "" }), {
    title: "Stopped",
    next: "another",
  });
});
