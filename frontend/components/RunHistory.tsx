"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

import {
  forgetRun,
  parseHistory,
  readHistoryRaw,
  subscribeToHistory,
} from "@/lib/history";
import { formatDateTime } from "@/lib/provenance";

export function RunHistory() {
  // The server can't see this device's history, so it renders nothing here.
  const raw = useSyncExternalStore(subscribeToHistory, readHistoryRaw, () => null);
  const entries = parseHistory(raw);
  if (entries.length === 0) return null;

  return (
    <section aria-labelledby="history-heading">
      <h2 id="history-heading" className="section-title">
        Your documents
      </h2>
      <p className="mt-1 text-sm text-muted">
        Open one to see it and listen again. This list is kept only on this
        device.
      </p>
      <ul className="mt-3 flex flex-col gap-2">
        {entries.map((entry) => (
          <li
            key={entry.runId}
            className="flex items-center gap-2 rounded-md border border-line bg-surface hover:border-accent"
          >
            <Link
              href={`/runs/${entry.runId}`}
              className="min-h-11 min-w-0 flex-1 rounded-md p-3 focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span className="block font-medium break-words">
                {entry.title ?? "Untitled document"}
              </span>
              <span className="block text-sm text-muted">
                {formatDateTime(entry.openedAt)}
                {entry.status === "failed" && " · Stopped"}
              </span>
            </Link>
            <button
              type="button"
              aria-label={`Remove ${entry.title ?? "this document"} from this list`}
              onClick={() => forgetRun(entry.runId)}
              className="min-h-11 shrink-0 rounded-md px-3 text-sm text-muted underline hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
