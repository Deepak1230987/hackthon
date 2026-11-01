"use client";

import { FileText, X } from "lucide-react";
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
      <h2 id="history-heading" className="text-2xl font-bold lg:text-3xl">
        Your documents
      </h2>
      <p className="mt-1 text-muted">
        Open one to see it and listen again. This list is kept only on this
        device.
      </p>
      <ul className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <li
            key={entry.runId}
            className="card flex items-start transition-colors hover:border-accent"
          >
            <Link
              href={`/runs/${entry.runId}`}
              className="flex min-h-11 min-w-0 flex-1 gap-3 rounded-2xl p-4"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <FileText aria-hidden className="size-5" />
              </span>
              <span className="min-w-0">
                <span className="block leading-snug font-semibold break-words">
                  {entry.title ?? "Untitled document"}
                </span>
                <span className="mt-0.5 block text-sm text-muted">
                  {formatDateTime(entry.openedAt)}
                  {entry.status === "failed" && " · Stopped"}
                </span>
              </span>
            </Link>
            <button
              type="button"
              aria-label={`Remove ${entry.title ?? "this document"} from this list`}
              onClick={() => forgetRun(entry.runId)}
              className="btn btn-ghost btn-icon m-1 shrink-0"
            >
              <X aria-hidden className="size-5" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
