"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Spinner } from "@/components/ui";
import { ApiRequestError, choosePageRange } from "@/lib/api";
import { pageRangeProblem } from "@/lib/pageRange";

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
    <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-3">
      <label className="flex w-28 flex-col gap-1 text-sm font-semibold">
        First page
        <input
          value={from}
          inputMode="numeric"
          onChange={(e) => setFrom(e.target.value)}
          className="field text-base font-normal"
        />
      </label>
      <label className="flex w-28 flex-col gap-1 text-sm font-semibold">
        Last page
        <input
          value={to}
          inputMode="numeric"
          onChange={(e) => setTo(e.target.value)}
          className="field text-base font-normal"
        />
      </label>
      <button type="submit" disabled={starting} className="btn btn-primary min-h-12">
        {starting ? <Spinner /> : <ArrowRight aria-hidden className="size-5" />}
        {starting ? "Starting…" : "Explain these pages"}
      </button>
      {error && (
        <p role="alert" className="w-full text-sm text-danger">
          {error}
        </p>
      )}
    </form>
  );
}
