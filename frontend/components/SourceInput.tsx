"use client";

import {
  ArrowRight,
  CircleCheck,
  FileText,
  LibraryBig,
  Link2,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { Notice, Skeleton, Spinner } from "@/components/ui";
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

const TABS: { id: "upload" | "link" | "library"; label: string; icon: LucideIcon; hint: string }[] = [
  { id: "upload", label: "Upload", icon: Upload, hint: "Choose a PDF to continue." },
  { id: "link", label: "Link", icon: Link2, hint: "Paste a link to continue." },
  { id: "library", label: "Library", icon: LibraryBig, hint: "Choose a document to continue." },
];

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
    <form onSubmit={onSubmit} className="flex flex-col gap-5 text-ink">
      <div>
        <h2 className="section-title mb-3">Which document?</h2>
        <div
          role="tablist"
          aria-label="Where the document comes from"
          onKeyDown={onTabKey}
          className="mb-3 grid grid-cols-3 gap-1 rounded-xl bg-sunken p-1"
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
              className={`flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-2 font-medium transition-colors ${
                tab === t.id
                  ? "bg-surface text-accent shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              <t.icon aria-hidden className="size-4 shrink-0" />
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
            className={`flex min-h-36 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${
              dragging
                ? "border-accent bg-accent-soft"
                : file
                  ? "border-success/50 bg-success-soft"
                  : "border-line-strong hover:border-accent hover:bg-accent-soft/50"
            }`}
          >
            {file ? (
              <>
                <FileText aria-hidden className="size-7 text-success" />
                <span className="font-semibold break-all">{file.name}</span>
                <span className="text-sm text-muted">
                  {formatSize(file.size)} · Tap to choose a different file
                </span>
              </>
            ) : (
              <>
                <Upload aria-hidden className="size-7 text-accent" />
                <span className="text-lg font-semibold">Choose a government PDF</span>
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
            className="field"
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
            <div role="status" className="flex flex-col gap-2">
              <span className="sr-only">Loading the library…</span>
              <Skeleton className="h-16 rounded-xl" />
              <Skeleton className="h-16 rounded-xl" />
              <Skeleton className="h-16 rounded-xl" />
            </div>
          )}
          {library.status === "failed" && (
            <Notice tone="danger" role="alert" title="We couldn't load the library.">
              <button
                type="button"
                onClick={() => void loadLibrary()}
                className="link min-h-11"
              >
                Try again
              </button>
            </Notice>
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
              <div className="-mx-1 flex max-h-72 flex-col gap-2 overflow-y-auto p-1">
                {library.documents.map((d) => (
                  <label
                    key={d.id}
                    className="flex cursor-pointer items-center gap-3 rounded-xl border border-line p-3 transition-colors hover:border-accent has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-accent"
                  >
                    <input
                      type="radio"
                      name="library-document"
                      value={d.id}
                      checked={libraryId === d.id}
                      onChange={() => setLibraryId(d.id)}
                      className="peer sr-only"
                    />
                    <FileText aria-hidden className="size-5 shrink-0 text-muted peer-checked:hidden" />
                    <CircleCheck aria-hidden className="hidden size-5 shrink-0 text-accent peer-checked:block" />
                    <span className="min-w-0">
                      <span className="block leading-snug font-medium break-words">
                        {d.title ?? sourceHost(d.source_url)}
                      </span>
                      <span className="mt-0.5 block text-sm text-muted break-words">
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
        <legend className="section-title mb-3">Explain it to me in</legend>
        <div className="grid grid-cols-2 gap-2">
          {LANGUAGES.map((l) => (
            <label
              key={l.code}
              className="flex min-h-14 cursor-pointer items-center justify-between gap-2 rounded-xl border border-line-strong px-4 py-2 transition-colors hover:border-accent has-checked:border-2 has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-accent"
            >
              <span className="flex flex-col leading-tight">
                <span lang={l.code} className="text-xl font-semibold">
                  {l.label}
                </span>
                <span className="text-sm text-muted">{l.english}</span>
              </span>
              <input
                type="radio"
                name="language"
                value={l.code}
                checked={language === l.code}
                onChange={() => setLanguage(l.code)}
                className="peer sr-only"
              />
              <CircleCheck aria-hidden className="hidden size-6 shrink-0 text-accent peer-checked:block" />
            </label>
          ))}
        </div>
      </fieldset>

      {error && (
        <Notice tone="danger" role="alert">
          {error}
        </Notice>
      )}

      <div>
        <button
          type="submit"
          disabled={!ready || submitting}
          className="btn btn-primary btn-lg w-full"
        >
          {submitting ? (
            <>
              <Spinner />
              {tab === "upload" ? "Uploading…" : "Starting…"}
            </>
          ) : (
            <>
              Explain this document
              <ArrowRight aria-hidden className="size-5" />
            </>
          )}
        </button>
        {!ready && (
          <p className="mt-1.5 text-center text-sm text-muted">
            {TABS.find((t) => t.id === tab)?.hint}
          </p>
        )}
      </div>

      <p className="text-sm text-muted">
        Documents are stored so they can be checked and reused, so use public
        documents only, not anything with personal details. Your answers to
        questions stay only in memory for this check, and voice recordings are
        never kept.
      </p>
    </form>
  );
}
