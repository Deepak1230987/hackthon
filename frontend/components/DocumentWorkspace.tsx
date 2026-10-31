"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { ClauseList } from "@/components/ClauseList";
import { PagePicker } from "@/components/PagePicker";
import { PdfViewer } from "@/components/PdfViewer";
import { ProvenanceBadge } from "@/components/ProvenanceBadge";
import { ApiRequestError, fetchClauses } from "@/lib/api";
import type { Clause, DocumentClauses, DocumentView } from "@/lib/types";

const DESKTOP = "(min-width: 1024px)";

function subscribeToDesktop(onChange: () => void): () => void {
  const query = window.matchMedia(DESKTOP);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

const isDesktopNow = () => window.matchMedia(DESKTOP).matches;
const isDesktopOnServer = () => false;

export function DocumentWorkspace({
  document: doc,
  clausesReady,
  children,
}: {
  document: DocumentView;
  clausesReady: boolean;
  children: ReactNode;
}) {
  const isDesktop = useSyncExternalStore(
    subscribeToDesktop,
    isDesktopNow,
    isDesktopOnServer,
  );
  const [data, setData] = useState<DocumentClauses | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Clause | undefined>();
  const [sheetOpen, setSheetOpen] = useState(false);
  // On a phone the PDF isn't downloaded until someone asks to see it.
  const [sheetUsed, setSheetUsed] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!clausesReady) return;
    let cancelled = false;
    fetchClauses(doc.id)
      .then((loaded) => {
        if (cancelled) return;
        setData(loaded);
        setLoadError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(
          e instanceof ApiRequestError
            ? e.message
            : "We couldn't load the clauses.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [doc.id, clausesReady, attempt]);

  const onPage = useMemo(
    () =>
      (data?.clauses ?? [])
        .filter((c) => c.page === page)
        .sort((a, b) => a.ordinal - b.ordinal),
    [data, page],
  );

  const changePage = useCallback((next: number) => {
    setPage(next);
    setSelected(undefined);
  }, []);

  const openSheet = () => {
    returnFocusRef.current = window.document.activeElement as HTMLElement;
    setSheetUsed(true);
    setSheetOpen(true);
  };

  const closeSheet = useCallback(() => {
    setSheetOpen(false);
    returnFocusRef.current?.focus();
  }, []);

  const select = (clause: Clause) => {
    setSelected(clause);
    setPage(clause.page);
    if (!isDesktop) openSheet();
  };

  const sheetShowing = sheetOpen && !isDesktop;

  useEffect(() => {
    if (!sheetShowing) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeSheet();
    };
    const body = window.document.body;
    const overflow = body.style.overflow;
    body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [sheetShowing, closeSheet]);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-6">
        {children}
        <ProvenanceBadge document={doc} />

        <section aria-labelledby="clauses-heading">
          <h2 id="clauses-heading" className="text-lg font-semibold">
            Clauses
            {data && (
              <span className="font-normal text-muted">
                {" "}
                · {data.clauses.length}
              </span>
            )}
          </h2>

          {data && data.failed_pages.length > 0 && (
            <p className="mt-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
              We couldn&apos;t read{" "}
              {data.failed_pages.length === 1 ? "page" : "pages"}{" "}
              {data.failed_pages.join(", ")}, so nothing on{" "}
              {data.failed_pages.length === 1 ? "it" : "them"} is used.
            </p>
          )}

          {loadError && (
            <div role="alert" className="mt-2 text-sm">
              <p className="text-danger">{loadError}</p>
              <button
                type="button"
                onClick={() => {
                  setLoadError(null);
                  setAttempt((n) => n + 1);
                }}
                className="min-h-11 font-semibold text-accent underline"
              >
                Try again
              </button>
            </div>
          )}

          {!data && !loadError && (
            <p className="mt-2 text-sm text-muted">
              {clausesReady
                ? "Loading clauses…"
                : "Clauses appear here once the document has been read."}
            </p>
          )}

          {data && (
            <div className="mt-3 flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <PagePicker
                  page={page}
                  pageCount={doc.page_count}
                  onChange={changePage}
                />
                <button
                  type="button"
                  onClick={openSheet}
                  className="min-h-11 rounded-md border border-line bg-surface px-3 text-sm font-medium hover:border-accent focus-visible:outline-2 focus-visible:outline-accent lg:hidden"
                >
                  View this page
                </button>
              </div>
              <ClauseList
                clauses={onPage}
                selectedId={selected?.id}
                pageFailed={data.failed_pages.includes(page)}
                onSelect={select}
              />
            </div>
          )}
        </section>
      </div>

      <div
        role={sheetShowing ? "dialog" : undefined}
        aria-modal={sheetShowing || undefined}
        aria-label="Document page"
        className={`${
          sheetOpen ? "fixed inset-0 z-40 flex" : "hidden"
        } min-w-0 flex-col overflow-hidden bg-surface lg:sticky lg:inset-auto lg:top-4 lg:z-auto lg:flex lg:h-[calc(100dvh-2rem)] lg:rounded-lg lg:border lg:border-line`}
      >
        <div className="flex justify-end border-b border-line p-2 lg:hidden">
          <button
            ref={closeRef}
            type="button"
            onClick={closeSheet}
            className="min-h-11 rounded-md px-4 font-semibold text-accent focus-visible:outline-2 focus-visible:outline-accent"
          >
            Close
          </button>
        </div>
        {(isDesktop || sheetUsed) && (
          <PdfViewer
            documentId={doc.id}
            page={page}
            pageCount={doc.page_count}
            clause={selected}
            onPageChange={changePage}
          />
        )}
      </div>
    </div>
  );
}
