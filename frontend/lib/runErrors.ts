import type { ApiError } from "./types";

export type NextStep = "retry" | "another" | "choose" | "range";

// What the screen offers for each code the backend can end a run with. An
// unknown code still shows its message, with a way to start again.
const NEXT_STEPS: Record<string, { title: string; next: NextStep }> = {
  SOURCE_UNREACHABLE: { title: "We couldn't reach that site", next: "another" },
  NOT_A_PDF: { title: "That link isn't a PDF", next: "another" },
  URL_BLOCKED: { title: "We can't fetch from that link", next: "another" },
  INVALID_URL: { title: "That link isn't valid", next: "another" },
  FILE_TOO_LARGE: { title: "That file is too large", next: "another" },
  UPLOAD_LOST: { title: "We lost your upload", next: "another" },
  PDF_INVALID: { title: "We couldn't open that PDF", next: "another" },
  PDF_ENCRYPTED: { title: "That PDF is password protected", next: "another" },
  DOC_TOO_LONG: { title: "Choose the pages to explain", next: "range" },
  NOT_A_POLICY: { title: "This doesn't look like a policy", next: "another" },
  NO_READABLE_TEXT: { title: "We couldn't find any text", next: "another" },
  MULTIPLE_PDFS: { title: "Choose a document", next: "choose" },
  PROVIDERS_UNAVAILABLE: { title: "Our AI services are busy", next: "retry" },
  RUN_TIMEOUT: { title: "This took too long", next: "retry" },
  INTERNAL_ERROR: { title: "Something went wrong", next: "retry" },
  RATE_LIMITED: { title: "Too many requests", next: "retry" },
  RUN_NOT_FOUND: { title: "We couldn't find that run", next: "another" },
  DOCUMENT_NOT_FOUND: { title: "We couldn't find that document", next: "another" },
};

export const KNOWN_ERROR_CODES = Object.keys(NEXT_STEPS);

export function errorStep(error: ApiError): { title: string; next: NextStep } {
  return NEXT_STEPS[error.code] ?? { title: "Stopped", next: "another" };
}
