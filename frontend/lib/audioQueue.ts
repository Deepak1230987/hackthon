import type { Sentence } from "./types";

// The next sentence with audio after this one. Flagged sentences have none, so
// they are skipped, and still shown as skipped in the list.
export function nextPlayable(
  sentences: Sentence[],
  afterOrdinal: number,
): Sentence | undefined {
  return sentences.find(
    (s) => s.ordinal > afterOrdinal && s.audio_path && s.guard_status === "passed",
  );
}

// Whether a later sentence could still get audio, so the player should wait for
// it and not stop.
export function moreMayCome(
  sentences: Sentence[],
  afterOrdinal: number,
  runFinished: boolean,
): boolean {
  if (runFinished) return false;
  return sentences.some(
    (s) =>
      s.ordinal > afterOrdinal && !s.audio_path && s.guard_status !== "flagged",
  );
}
