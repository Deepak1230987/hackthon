"use client";

import { ChevronRight, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Spinner } from "@/components/ui";
import { ApiRequestError, submitUrl } from "@/lib/api";
import { sourceHost } from "@/lib/provenance";
import type { SourceOption } from "@/lib/types";

// A page that links to several PDFs ends its run. Choosing one starts a new run.
export function SourceOptions({
  options,
  language,
}: {
  options: SourceOption[];
  language: string;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const choose = async (url: string) => {
    setPending(url);
    setError(null);
    try {
      const runId = await submitUrl(url, language);
      router.push(`/runs/${runId}`);
    } catch (e) {
      setError(
        e instanceof ApiRequestError
          ? e.message
          : "Something went wrong. Please try again.",
      );
      setPending(null);
    }
  };

  return (
    <div className="mt-4">
      <ul className="flex flex-col gap-2">
        {options.map((option) => (
          <li key={option.url}>
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => void choose(option.url)}
              className="flex min-h-14 w-full items-center gap-3 rounded-xl border border-line-strong bg-surface px-3 py-2 text-left break-words transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              <FileText aria-hidden className="size-5 shrink-0 text-accent" />
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">
                  {option.label || option.url.split("/").pop()}
                </span>
                <span className="block text-sm text-muted">
                  {sourceHost(option.url)}
                </span>
              </span>
              {pending === option.url ? (
                <Spinner className="size-5 shrink-0" />
              ) : (
                <ChevronRight aria-hidden className="size-5 shrink-0 text-muted" />
              )}
            </button>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
