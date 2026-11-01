import type { RunStatus } from "./types.ts";

// Kept on this device only. There are no accounts, so a list held on the server
// would show one person's documents to everyone. Titles only, never answers.
const KEY = "haq.history";
const CHANGED = "haq:history-changed";
const MAX_ENTRIES = 20;

export type HistoryEntry = {
  runId: string;
  title: string | null;
  status: RunStatus;
  openedAt: string;
};

export function parseHistory(raw: string | null): HistoryEntry[] {
  if (!raw) return [];
  try {
    const entries: unknown = JSON.parse(raw);
    if (!Array.isArray(entries)) return [];
    return entries.filter(
      (e) =>
        typeof e?.runId === "string" &&
        typeof e?.openedAt === "string" &&
        typeof e?.status === "string" &&
        (e?.title === null || typeof e?.title === "string"),
    );
  } catch {
    return [];
  }
}

// A run already listed keeps its place, so coming back to it doesn't reorder the list.
export function withEntry(
  entries: HistoryEntry[],
  entry: HistoryEntry,
): HistoryEntry[] {
  const found = entries.find((e) => e.runId === entry.runId);
  if (found) {
    return entries.map((e) =>
      e === found ? { ...entry, openedAt: found.openedAt } : e,
    );
  }
  return [entry, ...entries].slice(0, MAX_ENTRIES);
}

export function withoutEntry(
  entries: HistoryEntry[],
  runId: string,
): HistoryEntry[] {
  return entries.filter((e) => e.runId !== runId);
}

// Storage can be blocked, as in some private windows. History is then just empty.
export function readHistoryRaw(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function save(entries: HistoryEntry[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries));
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    // Nothing to do: the run itself is unaffected.
  }
}

export function rememberRun(entry: HistoryEntry): void {
  save(withEntry(parseHistory(readHistoryRaw()), entry));
}

export function forgetRun(runId: string): void {
  save(withoutEntry(parseHistory(readHistoryRaw()), runId));
}

export function subscribeToHistory(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  // Fires when another tab changes the list.
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}
