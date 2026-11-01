"use client";

import { useRouter } from "next/navigation";
import {
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  ApiRequestError,
  fetchLibrary,
  MAX_PDF_MB,
  startLibraryRun,
  submitUrl,
  uploadDocument,
} from "@/lib/api";
import { LANGUAGES } from "@/lib/languages";
import { formatDate, sourceHost } from "@/lib/provenance";
import type { DocumentView } from "@/lib/types";

const TABS = [
  { id: "upload", label: "Upload" },
  { id: "link", label: "Link" },
  { id: "library", label: "Library" },
] as const;

type TabId = (typeof TABS)[number]["id"];

type Library =
  | { status: "idle" | "loading" | "failed" }
  | { status: "ready"; documents: DocumentView[] };

function validate(file: File): string | null {
  const isPdf =
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "This file isn't a PDF. Choose a PDF file.";
  if (file.size > MAX_PDF_MB * 1024 * 1024) {
    return `This file is larger than ${MAX_PDF_MB} MB. Upload a smaller file.`;
  }
  return null;
}

function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export function SourceInput() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});
  const [tab, setTab] = useState<TabId>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [library, setLibrary] = useState<Library>({ status: "idle" });
  const [libraryId, setLibraryId] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>(LANGUAGES[0].code);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadLibrary = async () => {
    setLibrary({ status: "loading" });
    try {
      setLibrary({ status: "ready", documents: await fetchLibrary() });
    } catch {
      setLibrary({ status: "failed" });
    }
  };

  const showTab = (next: TabId) => {
    setTab(next);
    setError(null);
    if (next === "library" && library.status === "idle") void loadLibrary();
  };

  const onTabKey = (e: KeyboardEvent) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const index = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(index + step + TABS.length) % TABS.length].id;
    showTab(next);
    tabRefs.current[next]?.focus();
  };

  const choose = (chosen: File | undefined) => {
    if (!chosen) return;
    const problem = validate(chosen);
    setError(problem);
    setFile(problem ? null : chosen);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files[0]);
  };

  const ready =
    (tab === "upload" && file !== null) ||
    (tab === "link" && url.trim() !== "") ||
    (tab === "library" && libraryId !== null);

  const start = (): Promise<string> => {
    if (tab === "upload") return uploadDocument(file as File, language);
    if (tab === "link") return submitUrl(url.trim(), language);
    return startLibraryRun(libraryId as string, language);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const runId = await start();
      router.push(`/runs/${runId}`);
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Something went wrong. Please try again.",
      );
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6">
      <div>
        <div
          role="tablist"
          aria-label="Where the document comes from"
          onKeyDown={onTabKey}
          className="mb-4 flex gap-1 rounded-lg border border-line bg-surface p-1"
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[t.id] = el;
              }}
              id={`tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              onClick={() => showTab(t.id)}
              className={`min-h-11 flex-1 rounded-md px-3 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                tab === t.id
                  ? "bg-accent-soft text-accent"
                  : "text-muted hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div
          id="panel-upload"
          role="tabpanel"
          aria-labelledby="tab-upload"
          hidden={tab !== "upload"}
        >
          <label
            htmlFor="document"
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex min-h-44 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${
              dragging
                ? "border-accent bg-accent-soft"
                : "border-line bg-surface hover:border-accent"
            }`}
          >
            {file ? (
              <>
                <span className="font-semibold break-all">{file.name}</span>
                <span className="text-sm text-muted">
                  {formatSize(file.size)} · Tap to choose a different file
                </span>
              </>
            ) : (
              <>
                <span className="font-semibold">Choose a government PDF</span>
                <span className="text-sm text-muted">
                  or drag it here. Up to {MAX_PDF_MB} MB.
                </span>
              </>
            )}
          </label>
          <input
            ref={inputRef}
            id="document"
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            onChange={(e) => {
              choose(e.target.files?.[0]);
              // Lets the same file be chosen again after an error.
              e.target.value = "";
            }}
          />
        </div>

        <div
          id="panel-link"
          role="tabpanel"
          aria-labelledby="tab-link"
          hidden={tab !== "link"}
        >
          <label htmlFor="document-url" className="mb-2 block font-semibold">
            Link to a government PDF
          </label>
          <input
            id="document-url"
            type="text"
            inputMode="url"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            placeholder="https://"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="min-h-12 w-full rounded-md border border-line bg-surface px-3 focus-visible:outline-2 focus-visible:outline-accent"
          />
          <p className="mt-2 text-sm text-muted">
            A link to a PDF, or to a page that links to one. Some government
            sites block automatic downloads. If this one does, upload the PDF
            instead.
          </p>
        </div>

        <div
          id="panel-library"
          role="tabpanel"
          aria-labelledby="tab-library"
          hidden={tab !== "library"}
        >
          {(library.status === "idle" || library.status === "loading") && (
            <p role="status" className="text-muted">
              Loading the library…
            </p>
          )}
          {library.status === "failed" && (
            <div role="alert">
              <p className="text-danger">
                We couldn&apos;t load the library.
              </p>
              <button
                type="button"
                onClick={() => void loadLibrary()}
                className="min-h-11 font-semibold text-accent underline"
              >
                Try again
              </button>
            </div>
          )}
          {library.status === "ready" && library.documents.length === 0 && (
            <p className="text-muted">
              The library is empty. Upload a PDF or paste a link instead.
            </p>
          )}
          {library.status === "ready" && library.documents.length > 0 && (
            <fieldset>
              <legend className="mb-2 font-semibold">
                Official documents we have already fetched
              </legend>
              <div className="flex flex-col gap-2">
                {library.documents.map((d) => (
                  <label
                    key={d.id}
                    className="flex cursor-pointer items-start gap-3 rounded-md border border-line bg-surface p-3 has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-accent"
                  >
                    <input
                      type="radio"
                      name="library-document"
                      value={d.id}
                      checked={libraryId === d.id}
                      onChange={() => setLibraryId(d.id)}
                      className="mt-1 accent-accent"
                    />
                    <span className="min-w-0">
                      <span className="block font-medium break-words">
                        {d.title ?? sourceHost(d.source_url)}
                      </span>
                      <span className="block text-sm text-muted break-words">
                        {[
                          sourceHost(d.source_url),
                          `${d.page_count} ${d.page_count === 1 ? "page" : "pages"}`,
                          d.is_scanned && "mostly read with OCR",
                          `fetched ${formatDate(d.fetched_at.slice(0, 10))}`,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </div>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">
          Explain it to me in
        </legend>
        <div className="flex flex-wrap gap-2">
          {LANGUAGES.map((l) => (
            <label
              key={l.code}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-line bg-surface px-4 has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-accent"
            >
              <input
                type="radio"
                name="language"
                value={l.code}
                checked={language === l.code}
                onChange={() => setLanguage(l.code)}
                className="accent-accent"
              />
              <span lang={l.code}>{l.label}</span>
              <span className="text-sm text-muted">{l.english}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!ready || submitting}
        className="min-h-12 rounded-md bg-accent px-6 font-semibold text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-line disabled:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {submitting
          ? tab === "upload"
            ? "Uploading…"
            : "Starting…"
          : "Explain this document"}
      </button>

      <p className="text-sm text-muted">
        Documents are stored so they can be checked and reused, so use public
        documents only, not anything with personal details. Your answers to
        questions stay only in memory for this check, and voice recordings are
        never kept.
      </p>
    </form>
  );
}
