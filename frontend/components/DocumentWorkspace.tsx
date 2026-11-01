"use client";

import {
  BookOpenText,
  CalendarDays,
  CircleCheck,
  Clock3,
  FileText,
  Hand,
  Headphones,
  MessageCircleQuestion,
  ScanText,
  ScrollText,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { PlayerBar, Transcript, useNarration } from "@/components/AudioPlayer";
import { ClauseList } from "@/components/ClauseList";
import { EligibilityPanel } from "@/components/EligibilityPanel";
import { PagePicker } from "@/components/PagePicker";
import { PdfViewer } from "@/components/PdfViewer";
import { ProvenanceBadge } from "@/components/ProvenanceBadge";
import { QuestionBox } from "@/components/QuestionBox";
import { RightsCard } from "@/components/RightsCard";
import { RunProgress } from "@/components/RunProgress";
import { Notice, Skeleton, Spinner } from "@/components/ui";
import { ApiRequestError, fetchClauses } from "@/lib/api";
import { languageOf } from "@/lib/languages";
import { formatDate, isOldDocument, OLD_DOCUMENT_YEARS, sourceHost } from "@/lib/provenance";
import { isTerminal } from "@/lib/runReducer";
import type {
  Claim,
  ClaimField,
  Clause,
  ClauseRef,
  DocumentClauses,
  DocumentView,
  Question,
  RunStatus,
  Sentence,
  Step,
  Verdict,
} from "@/lib/types";

const DESKTOP = "(min-width: 1024px)";

function subscribeToDesktop(onChange: () => void): () => void {
  const query = window.matchMedia(DESKTOP);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

const isDesktopNow = () => window.matchMedia(DESKTOP).matches;
const isDesktopOnServer = () => false;

const TABS: { id: TabId; english: string; icon: LucideIcon }[] = [
  { id: "understand", english: "Understand", icon: Headphones },
  { id: "rights", english: "Your rights", icon: ScrollText },
  { id: "ask", english: "Ask", icon: MessageCircleQuestion },
  { id: "document", english: "Document", icon: BookOpenText },
];

type TabId = "understand" | "rights" | "ask" | "document";

const STATUS_PILLS: Record<RunStatus, { style: string; Icon?: LucideIcon }> = {
  queued: { style: "bg-sunken text-muted", Icon: Clock3 },
  running: { style: "bg-accent-soft text-accent" },
  waiting_input: { style: "bg-highlight-soft text-highlight-strong", Icon: Hand },
  completed: { style: "bg-success-soft text-success", Icon: CircleCheck },
  partial: { style: "bg-warning-soft text-warning", Icon: TriangleAlert },
  failed: { style: "bg-danger-soft text-danger", Icon: TriangleAlert },
};

function StatusPill({ status, text }: { status: RunStatus; text: string }) {
  const { style, Icon } = STATUS_PILLS[status];
  return (
    <span
      role="status"
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-semibold ${style}`}
    >
      {Icon ? <Icon aria-hidden className="size-4" /> : <Spinner className="size-4" />}
      {text}
    </span>
  );
}

function DocumentHeader({
  doc,
  status,
  statusText,
}: {
  doc: DocumentView;
  status: RunStatus;
  statusText: string;
}) {
  const host = sourceHost(doc.source_url);
  const facts: { icon: LucideIcon; text: string }[] = [
    { icon: FileText, text: `${doc.page_count} ${doc.page_count === 1 ? "page" : "pages"}` },
  ];
  if (doc.issue_date) facts.push({ icon: CalendarDays, text: formatDate(doc.issue_date) });
  if (doc.is_scanned) facts.push({ icon: ScanText, text: "Mostly read with OCR" });
  return (
    <header>
      <StatusPill status={status} text={statusText} />
      <h1 className="mt-2 text-2xl leading-tight font-bold text-balance break-words lg:text-3xl">
        {doc.title ?? "Your document"}
      </h1>
      <p className="mt-1 line-clamp-2 text-muted">
        {doc.fetch_method === "upload"
          ? "Uploaded by you. Not checked against an official site."
          : (doc.issuing_authority ?? host)}
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        {facts.map(({ icon: Icon, text }) => (
          <li key={text} className="flex items-center gap-1.5">
            <Icon aria-hidden className="size-4" />
            {text}
          </li>
        ))}
      </ul>
    </header>
  );
}

export function DocumentWorkspace({
  runId,
  document: doc,
  clausesReady,
  status,
  statusText,
  steps,
  claims,
  notStated,
  question,
  verdict,
  sentences,
  language,
  firstPage,
  trace,
  children,
}: {
  runId: string;
  document: DocumentView;
  clausesReady: boolean;
  status: RunStatus;
  statusText: string;
  steps: Step[];
  claims: Claim[];
  notStated: ClaimField[];
  question?: Question;
  verdict?: Verdict;
  sentences: Sentence[];
  language?: string;
  // Where a run over part of a long document starts.
  firstPage?: number;
  trace: ReactNode;
  children: ReactNode;
}) {
  const isDesktop = useSyncExternalStore(
    subscribeToDesktop,
    isDesktopNow,
    isDesktopOnServer,
  );
  const [tab, setTab] = useState<TabId>("understand");
  // A new question or verdict is what the person is waiting for, so it's brought forward.
  const arrivalKey = question?.name ?? verdict?.outcome;
  const [seenArrival, setSeenArrival] = useState(arrivalKey);
  if (arrivalKey !== seenArrival) {
    setSeenArrival(arrivalKey);
    if (arrivalKey) setTab("understand");
  }
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});
  const panelsRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<DocumentClauses | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState(firstPage ?? 1);
  // An id, because a claim can be clicked before the clause text has loaded.
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const selected = useMemo(
    () => data?.clauses.find((c) => c.id === selectedId),
    [data, selectedId],
  );
  const [sheetOpen, setSheetOpen] = useState(false);
  // On a phone the PDF isn't downloaded until someone asks to see it.
  const [sheetUsed, setSheetUsed] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const finished = isTerminal(status);

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
    setSelectedId(undefined);
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
    setSelectedId(clause.id);
    setPage(clause.page);
    if (!isDesktop) openSheet();
  };

  const showSource = (source: ClauseRef) => {
    setSelectedId(source.id);
    setPage(source.page);
    if (!isDesktop) openSheet();
  };

  // On a laptop the document is beside the words, so it turns to each sentence's
  // clause. A phone keeps the words on screen, and shows the source when asked.
  const followSentence = useCallback(
    (sentence: Sentence) => {
      if (!isDesktop) return;
      const claim = claims.find((c) => sentence.claim_ids.includes(c.id));
      const source = claim?.clauses[0];
      if (!source) return;
      setSelectedId(source.id);
      setPage(source.page);
    },
    [claims, isDesktop],
  );

  const narration = useNarration({ sentences, finished, onSentence: followSentence });

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
    // The page behind the sheet can't be tabbed to or read while it's open.
    const chrome = [...window.document.querySelectorAll<HTMLElement>("[data-app-chrome]")];
    chrome.forEach((el) => {
      el.inert = true;
    });
    window.addEventListener("keydown", onKey);
    return () => {
      body.style.overflow = overflow;
      chrome.forEach((el) => {
        el.inert = false;
      });
      window.removeEventListener("keydown", onKey);
    };
  }, [sheetShowing, closeSheet]);

  const showTab = (next: TabId) => {
    setTab(next);
    // Start the new tab at its top, not partway down where the last one was left.
    const panels = panelsRef.current;
    if (panels && panels.getBoundingClientRect().top < 0) {
      panels.scrollIntoView({ block: "start" });
    }
  };

  const onTabKey = (e: ReactKeyboardEvent) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const index = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(index + step + TABS.length) % TABS.length].id;
    showTab(next);
    tabRefs.current[next]?.focus();
  };

  const words = languageOf(language);
  const usableClaims = claims.filter((c) => c.clauses.length > 0).length;
  const badge: Partial<Record<TabId, ReactNode>> = {
    rights: usableClaims > 0 ? usableClaims : undefined,
  };

  return (
    <main className="mx-auto w-full max-w-[1680px] flex-1 lg:grid lg:grid-cols-2 xl:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
      <div
        inert={sheetShowing}
        className="flex min-w-0 flex-col px-4 pt-4 pb-4 lg:px-8 lg:pt-6 lg:pb-6"
      >
        <div className="flex flex-col gap-3">
          <DocumentHeader doc={doc} status={status} statusText={statusText} />
          {!finished && <RunProgress steps={steps} status={status} compact />}
          {isOldDocument(doc.issue_date) && (
            <Notice tone="warning">
              This document looks more than {OLD_DOCUMENT_YEARS} years old. The
              rules may have changed, so check the latest version with the issuing
              office.
            </Notice>
          )}
          {children}
        </div>

        <div
          role="tablist"
          aria-label="Sections of this document"
          onKeyDown={onTabKey}
          className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:sticky lg:top-14 lg:bottom-auto lg:z-20 lg:-mx-8 lg:mt-4 lg:flex lg:gap-1 lg:border-t-0 lg:border-b lg:bg-paper lg:px-8 lg:pb-0"
        >
          {TABS.map(({ id, english, icon: Icon }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                ref={(el) => {
                  tabRefs.current[id] = el;
                }}
                id={`run-tab-${id}`}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={`run-panel-${id}`}
                tabIndex={active ? 0 : -1}
                onClick={() => showTab(id)}
                className={`relative flex min-h-16 flex-col items-center justify-center gap-0.5 px-1 py-1.5 transition-colors lg:min-h-12 lg:flex-row lg:gap-2 lg:px-3 ${
                  active ? "text-accent" : "text-muted hover:text-ink"
                }`}
              >
                <span
                  aria-hidden
                  className={`absolute inset-x-3 top-0 h-0.5 rounded-full lg:top-auto lg:bottom-0 lg:inset-x-1 ${
                    active ? "bg-accent" : "bg-transparent"
                  }`}
                />
                <span className="relative">
                  <Icon aria-hidden className="size-5" />
                  {id === "understand" && question && (
                    <span
                      aria-hidden
                      className="absolute -top-0.5 -right-1 size-2.5 rounded-full border-2 border-surface bg-danger"
                    />
                  )}
                </span>
                <span
                  lang={language}
                  className={`text-sm leading-tight ${active ? "font-semibold" : "font-medium"}`}
                >
                  {words.tabs[id]}
                </span>
                <span className="text-xs leading-tight lg:hidden xl:inline lg:text-muted">
                  {english}
                </span>
                {badge[id] !== undefined && (
                  <span className="absolute top-1 right-[calc(50%-1.75rem)] rounded-full bg-accent-soft px-1.5 text-xs font-semibold text-accent lg:static">
                    {badge[id]}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div ref={panelsRef} className="scroll-mt-14 pt-4 lg:scroll-mt-26">
          <div
            id="run-panel-understand"
            role="tabpanel"
            aria-labelledby="run-tab-understand"
            hidden={tab !== "understand"}
          >
            <div className="flex flex-col gap-5">
              <EligibilityPanel
                runId={runId}
                language={language ?? "hi"}
                question={question}
                verdict={verdict}
                claims={claims}
                onShowSource={showSource}
              />
              {sentences.length > 0 ? (
                <Transcript
                  narration={narration}
                  sentences={sentences}
                  claims={claims}
                  language={language}
                  selectedClauseId={selectedId}
                  onShowSource={showSource}
                />
              ) : !finished ? (
                !question && (
                  <section className="card p-4 sm:p-5">
                    <h2 lang={language} className="section-title">
                      {words.explainedHeading}
                    </h2>
                    <p className="mt-1 text-muted">
                      Your explanation appears here once its points have passed the checks.
                    </p>
                    <div className="mt-4 flex flex-col gap-2.5">
                      <Skeleton className="h-4 w-11/12" />
                      <Skeleton className="h-4 w-4/5" />
                      <Skeleton className="h-4 w-9/12" />
                    </div>
                  </section>
                )
              ) : (
                <Notice tone="info" title="There is no spoken explanation for this run.">
                  {usableClaims > 0
                    ? "You can still see what we confirmed in the rights tab, and read the clauses in the document tab."
                    : "You can still read its clauses in the document tab."}
                </Notice>
              )}
              {(verdict || sentences.length > 0) && (
                <p className="text-sm text-muted">
                  <span lang={language} className="block font-medium text-ink">
                    {words.notLegalAdvice}
                  </span>
                  This is not legal advice. Confirm with the issuing office before you
                  rely on it.
                </p>
              )}
            </div>
          </div>

          <div
            id="run-panel-rights"
            role="tabpanel"
            aria-labelledby="run-tab-rights"
            hidden={tab !== "rights"}
          >
            <RightsCard
              status={status}
              claims={claims}
              notStated={notStated}
              selectedClauseId={selectedId}
              onShowSource={showSource}
            />
          </div>

          <div
            id="run-panel-ask"
            role="tabpanel"
            aria-labelledby="run-tab-ask"
            hidden={tab !== "ask"}
          >
            {status === "completed" || status === "partial" ? (
              <QuestionBox runId={runId} language={language} onShowSource={showSource} />
            ) : (
              <section>
                <h2 lang={language} className="section-title">
                  {words.askHeading}
                </h2>
                <p className="mt-1 text-muted">
                  {status === "failed"
                    ? "This run stopped, so questions aren't available for it."
                    : "You can ask questions as soon as the document has been checked."}
                </p>
              </section>
            )}
          </div>

          <div
            id="run-panel-document"
            role="tabpanel"
            aria-labelledby="run-tab-document"
            hidden={tab !== "document"}
          >
            <div className="flex flex-col gap-5">
              <section aria-labelledby="clauses-heading" className="card p-4 sm:p-5">
                <h2 id="clauses-heading" className="section-title">
                  Clauses
                  {data && (
                    <span className="font-normal text-muted">
                      {" "}
                      · {data.clauses.length}
                    </span>
                  )}
                </h2>
                <p className="mt-0.5 text-sm text-muted">
                  The document&apos;s own words. Tap one to find it on the page.
                </p>

                {data && data.failed_pages.length > 0 && (
                  <div className="mt-2">
                    <Notice tone="danger">
                      We couldn&apos;t read{" "}
                      {data.failed_pages.length === 1 ? "page" : "pages"}{" "}
                      {data.failed_pages.join(", ")}, so nothing on{" "}
                      {data.failed_pages.length === 1 ? "it" : "them"} is used.
                    </Notice>
                  </div>
                )}

                {loadError && (
                  <div className="mt-2">
                    <Notice tone="danger" role="alert" title={loadError}>
                      <button
                        type="button"
                        onClick={() => {
                          setLoadError(null);
                          setAttempt((n) => n + 1);
                        }}
                        className="link min-h-11"
                      >
                        Try again
                      </button>
                    </Notice>
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
                        className="btn btn-secondary lg:hidden"
                      >
                        <BookOpenText aria-hidden className="size-5" />
                        View this page
                      </button>
                    </div>
                    <ClauseList
                      clauses={onPage}
                      selectedId={selectedId}
                      pageFailed={data.failed_pages.includes(page)}
                      onSelect={select}
                    />
                  </div>
                )}
              </section>
              {trace && <div className="card p-4 sm:p-5">{trace}</div>}
              <ProvenanceBadge document={doc} />
            </div>
          </div>
        </div>

        {sentences.length > 0 && (
          <PlayerBar
            narration={narration}
            sentences={sentences}
            language={language}
            finished={finished}
          />
        )}
      </div>

      <div
        role={sheetShowing ? "dialog" : undefined}
        aria-modal={sheetShowing || undefined}
        aria-label="Document page"
        className={`${
          sheetOpen ? "fixed inset-0 z-50 flex" : "hidden"
        } min-w-0 flex-col overflow-hidden bg-surface lg:sticky lg:inset-auto lg:top-14 lg:z-auto lg:flex lg:h-[calc(100dvh-3.5rem)] lg:border-l lg:border-line`}
      >
        <div className="flex items-center justify-between gap-2 border-b border-line py-1 pr-1 pl-4 lg:hidden">
          <p className="min-w-0 truncate font-semibold">{doc.title ?? "Document page"}</p>
          <button
            ref={closeRef}
            type="button"
            onClick={closeSheet}
            className="btn btn-ghost shrink-0 px-3"
          >
            <X aria-hidden className="size-5" />
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
    </main>
  );
}
