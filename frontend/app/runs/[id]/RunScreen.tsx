"use client";

import { useEffect } from "react";

import { AgentTrace } from "@/components/AgentTrace";
import { DocumentWorkspace } from "@/components/DocumentWorkspace";
import { RunError } from "@/components/RunError";
import { rememberRun } from "@/lib/history";
import { errorStep } from "@/lib/runErrors";
import type { ConnectionState, RunStatus } from "@/lib/types";
import { isTerminal } from "@/lib/runReducer";
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

const DEFAULT_LANGUAGE = "hi";

export function RunScreen({ id }: { id: string }) {
  const { view, connection, loaded } = useRunStream(id);
  const notice = CONNECTION_TEXT[connection];
  const hasDocument = Boolean(view.document);
  const title = view.document?.title ?? null;

  // Only once there's a document, so a mistyped link or a failed fetch isn't listed.
  useEffect(() => {
    if (!hasDocument) return;
    rememberRun({
      runId: id,
      title,
      status: view.status,
      openedAt: new Date().toISOString(),
    });
  }, [id, hasDocument, title, view.status]);

  const summary = (
    <>
      <div>
        <h1 className="text-2xl font-semibold">
          {!loaded
            ? "Loading your run…"
            : view.error
              ? errorStep(view.error).title
              : STATUS_TEXT[view.status]}
        </h1>
        {notice && (
          <p role="status" className="mt-2 text-sm text-warning">
            {notice}
          </p>
        )}
      </div>

      {view.error && (
        <RunError
          error={view.error}
          sourceUrl={view.document?.source_url}
          language={view.language ?? DEFAULT_LANGUAGE}
        />
      )}
    </>
  );

  const trace = loaded && !(view.error && view.steps.length === 0) && (
    <AgentTrace steps={view.steps} finished={isTerminal(view.status)} />
  );

  if (!view.document) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {summary}
        {trace}
      </div>
    );
  }
  return (
    <DocumentWorkspace
      key={view.document.id}
      runId={id}
      document={view.document}
      clausesReady={view.clausesReady}
      status={view.status}
      claims={view.claims}
      notStated={view.notStated}
      question={view.question}
      verdict={view.verdict}
      sentences={view.sentences}
      language={view.language}
      trace={trace}
    >
      {summary}
    </DocumentWorkspace>
  );
}
