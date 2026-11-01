"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SourceOptions } from "@/components/SourceOptions";
import { ApiRequestError, submitUrl } from "@/lib/api";
import { errorStep } from "@/lib/runErrors";
import type { ApiError, SourceOption } from "@/lib/types";

// What a run that stopped offers next, by error code.
export function RunError({
  error,
  sourceUrl,
  language,
}: {
  error: ApiError;
  sourceUrl?: string | null;
  language: string;
}) {
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const { next } = errorStep(error);
  const options = (error.details?.options ?? []) as SourceOption[];
  const choosing = next === "choose" && options.length > 0;

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
    <div
      role="alert"
      className={`rounded-md border px-4 py-3 ${
        choosing ? "border-accent bg-accent-soft" : "border-danger/30 bg-danger-soft"
      }`}
    >
      <p className={choosing ? "" : "text-danger"}>{error.message}</p>
      {choosing && <SourceOptions options={options} language={language} />}
      {retryError && <p className="mt-2 text-sm text-danger">{retryError}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        {next === "retry" && sourceUrl && (
          <button
            type="button"
            disabled={retrying}
            onClick={() => void retry()}
            className="min-h-11 rounded-md bg-accent px-4 font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {retrying ? "Starting…" : "Try again"}
          </button>
        )}
        <Link
          href="/"
          className={`flex min-h-11 items-center font-semibold underline ${
            choosing ? "text-accent" : "text-danger"
          }`}
        >
          {next === "retry" ? "Use another document" : "Try another document"}
        </Link>
      </div>
    </div>
  );
}
