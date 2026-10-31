"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

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
    <div className="mt-3">
      <ul className="flex flex-col gap-2">
        {options.map((option) => (
          <li key={option.url}>
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => void choose(option.url)}
              className="min-h-11 w-full rounded-md border border-line bg-surface px-3 py-2 text-left text-sm text-ink break-words hover:border-accent disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span className="block font-medium">
                {option.label || option.url.split("/").pop()}
              </span>
              <span className="block text-xs text-muted">
                {sourceHost(option.url)}
              </span>
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
