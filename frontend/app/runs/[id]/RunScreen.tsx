"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { AgentTrace } from "@/components/AgentTrace";
import { AppBar, AppFooter } from "@/components/AppChrome";
import { DocumentWorkspace } from "@/components/DocumentWorkspace";
import { RunError } from "@/components/RunError";
import { RunProgress } from "@/components/RunProgress";
import { Notice, Spinner } from "@/components/ui";
import { rememberRun } from "@/lib/history";
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

function Bar({ title }: { title?: string | null }) {
  return (
    <AppBar>
      {title && (
        <p className="hidden min-w-0 flex-1 truncate border-l border-line pl-3 text-sm font-medium text-muted md:block">
          {title}
        </p>
      )}
      <Link
        href="/"
        className="btn btn-ghost ml-auto shrink-0 px-3 text-sm"
      >
        <Plus aria-hidden className="size-5" />
        New document
      </Link>
    </AppBar>
  );
}

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

  const connectionNotice = notice && (
    <Notice tone="warning" role="status">
      {notice}
    </Notice>
  );

  const queueNotice = view.queuePosition !== undefined && (
    <p role="status" className="text-muted">
      {view.queuePosition === 1
        ? "You're next. It starts as soon as a place is free."
        : `You're number ${view.queuePosition} in the queue.`}
    </p>
  );

  const errorCard = (standalone: boolean) =>
    view.error && (
      <RunError
        runId={id}
        error={view.error}
        sourceUrl={view.document?.source_url}
        language={view.language ?? DEFAULT_LANGUAGE}
        standalone={standalone}
      />
    );

  const trace = loaded && !(view.error && view.steps.length === 0) && (
    <AgentTrace steps={view.steps} finished={isTerminal(view.status)} />
  );

  // A run that stopped with nothing to show has one job left: say what to do next.
  const nothingToShow =
    view.claims.length === 0 && view.sentences.length === 0;

  if (!view.document || (view.error && nothingToShow)) {
    return (
      <>
        <Bar />
        <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-5 px-4 py-6 lg:py-12">
          {!loaded ? (
            <h1 className="flex items-center gap-3 text-2xl font-bold">
              <Spinner />
              Loading your document…
            </h1>
          ) : view.error ? (
            <>
              {view.document?.title && (
                <p className="font-medium text-muted">{view.document.title}</p>
              )}
              {errorCard(true)}
              {trace && (
                <details className="card p-4 sm:p-5">
                  <summary className="min-h-11 py-2 font-semibold">What we did before stopping</summary>
                  <div className="mt-4">{trace}</div>
                </details>
              )}
            </>
          ) : (
            <>
              <div>
                <h1 className="text-3xl leading-tight font-bold">{STATUS_TEXT[view.status]}</h1>
                {queueNotice}
              </div>
              {connectionNotice}
              <div className="card p-4 sm:p-5">
                <RunProgress steps={view.steps} status={view.status} />
              </div>
              {trace && view.steps.length > 0 && <div className="card p-4 sm:p-5">{trace}</div>}
            </>
          )}
        </main>
        <AppFooter />
      </>
    );
  }
  return (
    <>
      <Bar title={title} />
      <DocumentWorkspace
        key={view.document.id}
        runId={id}
        document={view.document}
        clausesReady={view.clausesReady}
        status={view.status}
        statusText={STATUS_TEXT[view.status]}
        steps={view.steps}
        claims={view.claims}
        notStated={view.notStated}
        question={view.question}
        verdict={view.verdict}
        sentences={view.sentences}
        language={view.language}
        firstPage={view.pageRange?.from}
        trace={trace}
      >
        {queueNotice}
        {connectionNotice}
        {errorCard(false)}
      </DocumentWorkspace>
      {/* Clears the phone's fixed navigation, and the player above it when there is one. */}
      <AppFooter className={`lg:pb-0 ${view.sentences.length > 0 ? "pb-44" : "pb-20"}`} />
    </>
  );
}
