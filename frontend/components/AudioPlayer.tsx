"use client";

import { useEffect, useRef, useState } from "react";

import { audioUrl } from "@/lib/api";
import { moreMayCome, nextPlayable } from "@/lib/audioQueue";
import { languageOf } from "@/lib/languages";
import type { Claim, ClauseRef, Sentence } from "@/lib/types";

const SPEEDS = [0.75, 1, 1.25, 1.5];

export function AudioPlayer({
  sentences,
  claims,
  language,
  finished,
  selectedClauseId,
  onShowSource,
}: {
  sentences: Sentence[];
  claims: Claim[];
  language?: string;
  finished: boolean;
  selectedClauseId?: string;
  onShowSource: (source: ClauseRef) => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [current, setCurrent] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  // Set when the player reached a sentence whose audio isn't ready yet.
  const [waitingAfter, setWaitingAfter] = useState<number | null>(null);
  const [english, setEnglish] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [failed, setFailed] = useState(false);

  const play = (sentence: Sentence) => {
    const audio = audioRef.current;
    if (!audio || !sentence.audio_path) return;
    audio.src = audioUrl(sentence.audio_path);
    audio.playbackRate = speed;
    setCurrent(sentence.ordinal);
    setWaitingAfter(null);
    setFailed(false);
    // A browser can refuse to play. The text stays there to read.
    audio.play().catch(() => setFailed(true));
  };

  const playNext = (after: number) => {
    const next = nextPlayable(sentences, after);
    if (next) {
      play(next);
    } else if (moreMayCome(sentences, after, finished)) {
      setWaitingAfter(after);
    } else {
      setCurrent(null);
    }
  };

  // Carry on as soon as the sentence the player was waiting for has its audio.
  useEffect(() => {
    if (waitingAfter === null) return;
    const next = nextPlayable(sentences, waitingAfter);
    const audio = audioRef.current;
    if (!next?.audio_path || !audio) return;
    audio.src = audioUrl(next.audio_path);
    audio.playbackRate = speed;
    audio.play().catch(() => undefined);
    const id = setTimeout(() => {
      setCurrent(next.ordinal);
      setWaitingAfter(null);
    }, 0);
    return () => clearTimeout(id);
  }, [sentences, waitingAfter, speed]);

  if (sentences.length === 0) return null;

  const ready = sentences.some((s) => s.audio_path);
  const preparing = sentences.filter((s) => s.guard_status === "pending").length;
  const showSource = (sentence: Sentence) => {
    const claim = claims.find((c) => sentence.claim_ids.includes(c.id));
    if (claim?.clauses[0]) onShowSource(claim.clauses[0]);
  };

  return (
    <section aria-labelledby="audio-heading">
      <h2 id="audio-heading" className="text-lg font-semibold">
        Listen to the explanation
      </h2>

      <audio
        ref={audioRef}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          if (current !== null) playNext(current);
        }}
        onError={() => setFailed(true)}
      />

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!ready}
          onClick={() => {
            const audio = audioRef.current;
            if (playing) audio?.pause();
            else if (current !== null && audio?.src) audio.play().catch(() => setFailed(true));
            else playNext(-1);
          }}
          className="min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-line disabled:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {playing ? "Pause" : current !== null ? "Resume" : "Play"}
        </button>
        <label className="flex items-center gap-2 text-sm text-muted">
          Speed
          <select
            value={speed}
            onChange={(e) => {
              const next = Number(e.target.value);
              setSpeed(next);
              if (audioRef.current) audioRef.current.playbackRate = next;
            }}
            className="min-h-11 rounded-md border border-line bg-surface px-2 text-ink"
          >
            {SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value}×
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-pressed={english}
          onClick={() => setEnglish((on) => !on)}
          className="min-h-11 rounded-md border border-line bg-surface px-3 text-sm font-medium hover:border-accent focus-visible:outline-2 focus-visible:outline-accent"
        >
          {english ? `Show ${languageOf(language).english}` : "Show English"}
        </button>
      </div>

      {preparing > 0 && !finished && (
        <p role="status" className="mt-2 text-sm text-muted">
          Preparing {preparing} {preparing === 1 ? "sentence" : "sentences"}…
        </p>
      )}
      {finished && !ready && (
        <p className="mt-2 text-sm text-warning">
          Audio isn&apos;t available right now, so please read the explanation
          below.
        </p>
      )}
      {failed && (
        <p role="alert" className="mt-2 text-sm text-warning">
          We couldn&apos;t play this audio. You can read it below.
        </p>
      )}

      <ol className="mt-3 flex flex-col gap-1.5">
        {sentences
          .filter((s) => s.guard_status !== "pending")
          .map((sentence) => {
            const flagged = sentence.guard_status === "flagged";
            const speaking = current === sentence.ordinal;
            const showEnglish = english || flagged || !sentence.translated_text;
            const sourced = claims
              .filter((c) => sentence.claim_ids.includes(c.id))
              .some((c) => c.clauses.some((clause) => clause.id === selectedClauseId));
            return (
              <li key={sentence.id}>
                <button
                  type="button"
                  aria-current={speaking ? "true" : undefined}
                  onClick={() => {
                    showSource(sentence);
                    if (sentence.audio_path) play(sentence);
                  }}
                  className={`w-full rounded-md border px-3 py-2 text-left break-words focus-visible:outline-2 focus-visible:outline-accent ${
                    speaking || sourced
                      ? "border-highlight-strong bg-highlight-soft"
                      : "border-line bg-surface hover:border-accent"
                  }`}
                >
                  <span lang={showEnglish ? "en" : language} className="block">
                    {showEnglish ? sentence.source_text : sentence.translated_text}
                  </span>
                  {flagged && (
                    <span className="mt-1 block text-sm font-medium text-warning">
                      We couldn&apos;t confirm the translation of this sentence,
                      so it&apos;s shown in English and not read aloud.
                    </span>
                  )}
                </button>
              </li>
            );
          })}
      </ol>
    </section>
  );
}
