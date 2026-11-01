"use client";

import { CircleAlert, FileStack, RotateCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageRangeForm } from "@/components/PageRangeForm";
import { SourceOptions } from "@/components/SourceOptions";
import { Spinner } from "@/components/ui";
import { ApiRequestError, submitUrl } from "@/lib/api";
import { errorStep } from "@/lib/runErrors";
import type { ApiError, SourceOption } from "@/lib/types";

// What a run that stopped offers next, by error code.
export function RunError({
  runId,
  error,
  sourceUrl,
  language,
  standalone = false,
}: {
  runId: string;
  error: ApiError;
  sourceUrl?: string | null;
  language: string;
  // True when this is the whole page, so it carries the page's heading.
  standalone?: boolean;
}) {
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const { title, next } = errorStep(error);
  const options = (error.details?.options ?? []) as SourceOption[];
  const pageCount = error.details?.page_count;
  const maxPages = error.details?.max_pages;
  const hasRange =
    next === "range" && typeof pageCount === "number" && typeof maxPages === "number";
  const choosing = hasRange || (next === "choose" && options.length > 0);
  const Heading = standalone ? "h1" : "h2";
  const Icon = choosing ? FileStack : CircleAlert;

  const retry = async () => {
    if (!sourceUrl) return;
    setRetrying(true);
    setRetryError(null);
    try {
      router.push(`/runs/${await submitUrl(sourceUrl, language)}`);
    } catch (e) {
      setRetryError(
        e instanceof ApiRequestError ? e.message : "Something went wrong. Please try again.",
      );
      setRetrying(false);
    }
  };

  return (
    <div role="alert" className="card overflow-hidden">
      <div className="p-4 sm:p-6">
        <span
          className={`flex size-11 items-center justify-center rounded-xl ${
            choosing ? "bg-accent-soft text-accent" : "bg-danger-soft text-danger"
          }`}
        >
          <Icon aria-hidden className="size-6" />
        </span>
        <Heading className={`mt-3 font-bold ${standalone ? "text-3xl" : "text-xl"}`}>
          {title}
        </Heading>
        <p className="mt-1 text-lg text-muted">{error.message}</p>
        {next === "choose" && choosing && <SourceOptions options={options} language={language} />}
        {hasRange && <PageRangeForm runId={runId} pageCount={pageCount} maxPages={maxPages} />}
        {retryError && <p className="mt-2 text-sm text-danger">{retryError}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {next === "retry" && sourceUrl && (
            <button
              type="button"
              disabled={retrying}
              onClick={() => void retry()}
              className="btn btn-primary"
            >
              {retrying ? <Spinner /> : <RotateCw aria-hidden className="size-5" />}
              {retrying ? "Starting…" : "Try again"}
            </button>
          )}
          <Link href="/" className={next === "another" ? "btn btn-primary" : "btn btn-secondary"}>
            {next === "retry" ? "Use another document" : "Try another document"}
          </Link>
        </div>
      </div>
    </div>
  );
}
