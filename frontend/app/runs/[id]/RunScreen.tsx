"use client";

import Link from "next/link";

import { AgentTrace } from "@/components/AgentTrace";
import type { ConnectionState, RunStatus } from "@/lib/types";
import { useRunStream } from "@/lib/useRunStream";

const STATUS_TEXT: Record<RunStatus, string> = {
  queued: "In the queue",
  running: "Working on your document",
  waiting_input: "Waiting for your answer",
  completed: "Finished",
  partial: "Finished with partial results",
  failed: "Stopped",
};

const CONNECTION_TEXT: Partial<Record<ConnectionState, string>> = {
  reconnecting: "Connection lost. Reconnecting…",
  polling: "Live updates are unavailable. Checking every few seconds.",
};

export function RunScreen({ id }: { id: string }) {
  const { view, connection, loaded } = useRunStream(id);
  const notice = CONNECTION_TEXT[connection];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">
          {loaded ? STATUS_TEXT[view.status] : "Loading your run…"}
        </h1>
        {notice && (
          <p role="status" className="mt-2 text-sm text-warning">
            {notice}
          </p>
        )}
      </div>

      {view.error && (
        <div
          role="alert"
          className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3"
        >
          <p className="text-danger">{view.error.message}</p>
          <Link
            href="/"
            className="mt-2 inline-block font-semibold text-danger underline"
          >
            Try another document
          </Link>
        </div>
      )}

      {loaded && !(view.error && view.steps.length === 0) && (
        <AgentTrace steps={view.steps} />
      )}
    </div>
  );
}
