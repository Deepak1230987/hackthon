// PDF.js loads its worker, fonts, character maps and image decoders by URL, so
// they are served from public/ at the exact version that is installed.
import { cpSync, rmSync } from "node:fs";

const from = "node_modules/pdfjs-dist";
const to = "public/pdfjs";

rmSync(to, { recursive: true, force: true });
cpSync(`${from}/legacy/build/pdf.worker.min.mjs`, `${to}/pdf.worker.min.mjs`);
for (const folder of ["cmaps", "standard_fonts", "wasm"]) {
  cpSync(`${from}/${folder}`, `${to}/${folder}`, { recursive: true });
}
