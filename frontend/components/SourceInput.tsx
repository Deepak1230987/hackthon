"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type DragEvent, type FormEvent } from "react";

import { ApiRequestError, MAX_PDF_MB, uploadDocument } from "@/lib/api";

const LANGUAGES = [{ code: "hi-IN", label: "हिन्दी", english: "Hindi" }];

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
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState(LANGUAGES[0].code);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);

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

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const runId = await uploadDocument(file, language);
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
        disabled={!file || submitting}
        className="min-h-12 rounded-md bg-accent px-6 font-semibold text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-line disabled:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {submitting ? "Uploading…" : "Explain this document"}
      </button>

      <p className="text-sm text-muted">
        Uploaded documents are stored so they can be checked and reused. Upload
        public documents only, not anything with personal details.
      </p>
    </form>
  );
}
