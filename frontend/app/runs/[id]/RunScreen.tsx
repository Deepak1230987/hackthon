"use client";

import Link from "next/link";
import { useEffect } from "react";

import { AgentTrace } from "@/components/AgentTrace";
import { DocumentWorkspace } from "@/components/DocumentWorkspace";
import { SourceOptions } from "@/components/SourceOptions";
import { rememberRun } from "@/lib/history";
import type { ConnectionState, RunStatus, SourceOption } from "@/lib/types";
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
  const options = (view.error?.details?.options ?? []) as SourceOption[];
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
          {view.error.code === "MULTIPLE_PDFS" && options.length > 0 && (
            <SourceOptions
              options={options}
              language={view.language ?? DEFAULT_LANGUAGE}
            />
          )}
          <Link
            href="/"
            className="mt-2 inline-block font-semibold text-danger underline"
          >
            Try another document
          </Link>
        </div>
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
