"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ApiRequestError, choosePageRange } from "@/lib/api";
import { pageRangeProblem } from "@/lib/pageRange";

const INPUT =
  "min-h-11 w-24 rounded-md border border-line bg-surface px-3 focus-visible:outline-2 focus-visible:outline-accent";

export function PageRangeForm({
  runId,
  pageCount,
  maxPages,
}: {
  runId: string;
  pageCount: number;
  maxPages: number;
}) {
  const router = useRouter();
  const [from, setFrom] = useState("1");
  const [to, setTo] = useState(String(Math.min(maxPages, pageCount)));
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const first = from.trim() === "" ? Number.NaN : Number(from);
    const last = to.trim() === "" ? Number.NaN : Number(to);
    const problem = pageRangeProblem(first, last, pageCount, maxPages);
    setError(problem);
    if (problem) return;
    setStarting(true);
    try {
      router.push(`/runs/${await choosePageRange(runId, first, last)}`);
    } catch (err) {
      setError(
        err instanceof ApiRequestError ? err.message : "Something went wrong. Please try again.",
      );
      setStarting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="mt-3 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-sm font-semibold text-ink">
        First page
        <input
          value={from}
          inputMode="numeric"
          onChange={(e) => setFrom(e.target.value)}
          className={`${INPUT} font-normal`}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-semibold text-ink">
        Last page
        <input
          value={to}
          inputMode="numeric"
          onChange={(e) => setTo(e.target.value)}
          className={`${INPUT} font-normal`}
        />
      </label>
      <button
        type="submit"
        disabled={starting}
        className="min-h-11 rounded-md bg-accent px-4 font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {starting ? "Starting…" : "Explain these pages"}
      </button>
      {error && <p className="w-full text-sm text-danger">{error}</p>}
    </form>
  );
}
