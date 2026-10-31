import type { RunEvent } from "./types";

export type Tone = "plain" | "good" | "warn" | "bad";

export type TraceLine = { key: number; text: string; tone: Tone };

const FETCH_METHODS: Record<string, string> = {
  http: "Downloading from the site",
  browser: "Opening the site in a browser",
  upload: "Using your upload",
};

function pageList(pages: unknown[]): string {
  const label = pages.length === 1 ? "page" : "pages";
  return `${label} ${pages.join(", ")}`;
}

function describe(event: RunEvent): Omit<TraceLine, "key"> {
  const p = event.payload;
  const suffix = (value: unknown) => (value ? `: ${String(value)}` : "");
  switch (event.type) {
    case "fetch_attempt":
      return {
        text: FETCH_METHODS[String(p.method)] ?? "Getting the document",
        tone: "plain",
      };
    case "segment_done":
      return { text: `Found ${p.clauses ?? "?"} clauses`, tone: "plain" };
    case "embeddings_done":
      return p.embedded
        ? { text: "Prepared the clauses for search", tone: "plain" }
        : { text: "Search isn't ready yet. The next run retries it", tone: "warn" };
    case "triage_result":
      return {
        text: p.is_policy ? "This is a policy document" : "Not a policy document",
        tone: p.is_policy ? "good" : "warn",
      };
    case "claim_extracted":
      return { text: `Claim extracted${suffix(p.field)}`, tone: "plain" };
    case "claim_verified":
      return { text: "Claim verified", tone: "good" };
    case "claim_rejected":
      return { text: `Claim rejected${suffix(p.reason)}`, tone: "bad" };
    case "retry":
      return { text: `Retrying${suffix(p.reason)}`, tone: "warn" };
    case "rules_compiled":
      return { text: `Compiled ${p.count ?? "?"} rules`, tone: "plain" };
    case "needs_input":
      return { text: "Waiting for your answer", tone: "warn" };
    case "verdict":
      return { text: `Result${suffix(p.outcome)}`, tone: "plain" };
    case "script_ready":
      return { text: `Script has ${p.sentences ?? "?"} sentences`, tone: "plain" };
    case "sentence_translated":
      return { text: `Sentence translated${suffix(p.translator)}`, tone: "plain" };
    case "failover":
      return {
        text: `Switched provider${p.to ? ` to ${String(p.to)}` : ""}`,
        tone: "warn",
      };
    case "guard_failed":
      return { text: `Guard failed${suffix(p.reason)}`, tone: "bad" };
    case "sentence_ready":
      return { text: "Sentence audio ready", tone: "good" };
    default:
      return { text: event.type, tone: "plain" };
  }
}

// A long scan sends an event per page, so OCR is shown as one running count.
export function traceLines(events: RunEvent[]): TraceLine[] {
  const lines: TraceLine[] = [];
  const started = new Set<unknown>();
  const failed = new Set<unknown>();
  let ocrLine: TraceLine | undefined;

  for (const event of events) {
    if (event.type === "page_ocr") {
      (event.payload.failed ? failed : started).add(event.payload.page);
      if (!ocrLine) {
        ocrLine = { key: event.seq, text: "", tone: "plain" };
        lines.push(ocrLine);
      }
      continue;
    }
    lines.push({ key: event.seq, ...describe(event) });
    const unread = event.payload.failed_pages;
    if (
      event.type === "segment_done" &&
      Array.isArray(unread) &&
      unread.length > 0
    ) {
      lines.push({
        key: event.seq + 0.5,
        text: `Couldn't read ${pageList(unread)}`,
        tone: "bad",
      });
    }
  }

  if (ocrLine) {
    ocrLine.text = `Read ${started.size} ${
      started.size === 1 ? "page" : "pages"
    } with OCR`;
    if (failed.size > 0) {
      ocrLine.text += `. Couldn't read ${pageList([...failed])}`;
      ocrLine.tone = "bad";
    }
  }
  return lines;
}
