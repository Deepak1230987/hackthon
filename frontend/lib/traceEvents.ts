import type { RunEvent, Step } from "./types";

export type Tone = "plain" | "good" | "warn" | "bad";

export type TraceLine = { key: number; text: string; tone: Tone };

const FETCH_METHODS: Record<string, string> = {
  http: "Downloading from the site",
  browser: "Opening the site in a browser",
  upload: "Using your upload",
};

const REJECTION_REASONS: Record<string, string> = {
  QUOTE_NOT_IN_SOURCE: "the quote isn't in the cited clause",
  QUOTE_TOO_SHORT: "the quote is too short to check",
  NUMBER_NOT_IN_QUOTE: "a number isn't in the quote",
  CLAUSE_NOT_FOUND: "the cited clause doesn't exist",
  PARTIAL: "the clause only partly supports it",
  NOT_ENTAILED: "the clause doesn't support it",
  BUDGET_EXHAUSTED: "this run reached its limit before checking it",
  PROVIDERS_UNAVAILABLE: "the AI provider couldn't check it",
};

// These say the check couldn't run. They say nothing about whether the claim is right.
const UNCHECKED_REASONS = new Set(["BUDGET_EXHAUSTED", "PROVIDERS_UNAVAILABLE"]);

const GUARD_REASONS: Record<string, string> = {
  NUMBER_CHANGED: "a number changed in translation",
  MEANING_CHANGED: "the meaning changed in translation",
  MEANING_UNCHECKED: "the meaning couldn't be checked",
  NOT_TRANSLATED: "it couldn't be translated",
};

const OUTCOME_TEXT: Record<string, string> = {
  MEETS_STATED_CRITERIA: "You appear to meet the stated criteria",
  DOES_NOT_MEET: "You don't appear to meet a criterion",
  NEEDS_INFO: "More details are needed",
  CANNOT_DETERMINE: "This document can't settle eligibility",
};

function sentenceCount(count: number): string {
  return `${count} ${count === 1 ? "sentence" : "sentences"}`;
}

function claimCount(count: number): string {
  return `${count} ${count === 1 ? "claim" : "claims"}`;
}

function pageList(pages: unknown[]): string {
  const label = pages.length === 1 ? "page" : "pages";
  return `${label} ${pages.join(", ")}`;
}

function describe(event: RunEvent): Omit<TraceLine, "key"> {
  const p = event.payload;
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
    case "rules_compiled":
      return { text: `Compiled ${p.count ?? "?"} rules`, tone: "plain" };
    case "needs_input":
      return { text: "Waiting for your answer", tone: "warn" };
    case "verdict":
      return { text: OUTCOME_TEXT[String(p.outcome)] ?? "Eligibility checked", tone: "plain" };
    case "script_ready":
      return { text: `Script has ${p.sentences ?? "?"} sentences`, tone: "plain" };
    case "failover":
      return {
        text: `${String(p.from ?? "The AI provider")} failed${
          p.reason ? ` (${String(p.reason)})` : ""
        }, so we switched to ${String(p.to ?? "another provider")}`,
        tone: "warn",
      };
    default:
      return { text: event.type, tone: "plain" };
  }
}

// Long runs send an event per page and per claim, so these are shown as running counts.
export function traceLines(events: RunEvent[], attempt = 1): TraceLine[] {
  const lines: TraceLine[] = [];
  const counted = new Map<string, TraceLine & { count: number }>();

  const count = (event: RunEvent, id: string, tone: Tone) => {
    let line = counted.get(id);
    if (!line) {
      line = { key: event.seq, text: "", tone, count: 0 };
      counted.set(id, line);
      lines.push(line);
    }
    line.count += 1;
  };

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
    if (event.type === "claim_extracted") {
      count(event, "extracted", "plain");
      continue;
    }
    if (event.type === "claim_verified") {
      count(event, "verified", "good");
      continue;
    }
    if (event.type === "retry") {
      count(event, "retry", "warn");
      continue;
    }
    if (event.type === "sentence_translated") {
      count(event, "translated", "plain");
      continue;
    }
    if (event.type === "sentence_ready") {
      count(event, "spoken", "good");
      continue;
    }
    if (event.type === "guard_failed") {
      count(event, `guard:${String(event.payload.reason)}`, "bad");
      continue;
    }
    if (event.type === "claim_rejected") {
      const reason = String(event.payload.reason);
      count(
        event,
        `rejected:${reason}`,
        UNCHECKED_REASONS.has(reason) ? "warn" : "bad",
      );
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
  for (const [id, line] of counted) {
    const claims = claimCount(line.count);
    const sentences = sentenceCount(line.count);
    if (id === "translated") {
      line.text = `Translated ${sentences}`;
    } else if (id === "spoken") {
      line.text = `${sentences} ready to hear`;
    } else if (id.startsWith("guard:")) {
      const reason = id.slice("guard:".length);
      line.text = `Caught ${sentences}: ${GUARD_REASONS[reason] ?? reason}`;
    } else if (id === "extracted") {
      line.text = attempt > 1 ? `Rewrote ${claims}` : `Extracted ${claims}`;
    } else if (id === "verified") {
      line.text = `${claims} passed every check`;
    } else if (id === "retry") {
      line.text = `Sent ${line.count} back to be corrected`;
    } else {
      const reason = id.slice("rejected:".length);
      const why = REJECTION_REASONS[reason] ?? reason;
      line.text = UNCHECKED_REASONS.has(reason)
        ? `Couldn't check ${claims}: ${why}`
        : `Rejected ${claims}: ${why}`;
    }
  }
  return lines.map(({ key, text, tone }) => ({ key, text, tone }));
}

export type CorrectionSummary = {
  rejected: number;
  corrected: number;
  unresolved: number;
  unchecked: number;
};

// Follows each claim across attempts, since a rejected claim keeps its id when corrected.
export function correctionSummary(steps: Step[]): CorrectionSummary {
  const rejected = new Set<unknown>();
  const unchecked = new Set<unknown>();
  const verified = new Set<unknown>();
  for (const step of steps) {
    for (const event of step.events) {
      if (event.type === "claim_verified") verified.add(event.payload.claim_id);
      if (event.type !== "claim_rejected") continue;
      const isUnchecked = UNCHECKED_REASONS.has(String(event.payload.reason));
      (isUnchecked ? unchecked : rejected).add(event.payload.claim_id);
    }
  }
  const corrected = [...rejected].filter((id) => verified.has(id)).length;
  const neverVerified = (ids: Set<unknown>) =>
    [...ids].filter((id) => !verified.has(id));
  return {
    rejected: rejected.size,
    corrected,
    // A claim that was rejected, corrected and then couldn't be checked counts once, as unchecked.
    unresolved: neverVerified(rejected).filter((id) => !unchecked.has(id)).length,
    unchecked: neverVerified(unchecked).length,
  };
}
