import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

test("committed PDF.js files match the installed version", () => {
  const committed = readFileSync("public/pdfjs/pdf.worker.min.mjs");
  const installed = readFileSync(
    "node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs",
  );
  assert.ok(
    committed.equals(installed),
    "Run npm run pdfjs:copy and commit public/pdfjs.",
  );
});
