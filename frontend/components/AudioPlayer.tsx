"use client";

import { Pause, Play, SkipBack, SkipForward, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";

import { SourceChip } from "@/components/ui";
import { audioUrl } from "@/lib/api";
import { moreMayCome, nextPlayable } from "@/lib/audioQueue";
import { languageOf } from "@/lib/languages";
import type { Claim, ClauseRef, Sentence } from "@/lib/types";

const SPEEDS = [0.75, 1, 1.25, 1.5];

export type Narration = {
  audioRef: RefObject<HTMLAudioElement | null>;
  current: number | null;
  playing: boolean;
  waitingAfter: number | null;
  english: boolean;
  setEnglish: (on: boolean) => void;
  speed: number;
  cycleSpeed: () => void;
  failed: boolean;
  setFailed: (failed: boolean) => void;
  setPlaying: (playing: boolean) => void;
  play: (sentence: Sentence) => void;
  playNext: (after: number) => void;
};

// Lives above the tabs, so the voice and its controls carry on whichever one is open.
export function useNarration({
  sentences,
  finished,
  onSentence,
}: {
  sentences: Sentence[];
  finished: boolean;
  // Called when a sentence starts, so the document can follow along.
  onSentence?: (sentence: Sentence) => void;
}): Narration {
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
    onSentence?.(sentence);
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
      onSentence?.(next);
    }, 0);
    return () => clearTimeout(id);
  }, [sentences, waitingAfter, speed, onSentence]);

  const cycleSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    setSpeed(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
  };

  return {
    audioRef,
    current,
    playing,
    waitingAfter,
    english,
    setEnglish,
    speed,
    cycleSpeed,
    failed,
    setFailed,
    setPlaying,
    play,
    playNext,
  };
}

function sentenceText(sentence: Sentence, english: boolean): string {
  const showEnglish = english || sentence.guard_status === "flagged" || !sentence.translated_text;
  return showEnglish ? sentence.source_text : (sentence.translated_text as string);
}

const NIGHT_ICON_BUTTON =
  "hidden size-11 shrink-0 items-center justify-center rounded-full text-white hover:bg-white/15 disabled:opacity-40 sm:flex";

// Stays on screen on every tab: above the navigation on a phone, at the foot of the column on a laptop.
export function PlayerBar({
  narration,
  sentences,
  language,
  finished,
}: {
  narration: Narration;
  sentences: Sentence[];
  language?: string;
  finished: boolean;
}) {
  const { audioRef, current, playing, speed, failed, english } = narration;
  const words = languageOf(language);
  const ready = sentences.some((s) => s.audio_path);
  const preparing = sentences.filter((s) => s.guard_status === "pending").length;
  const speaking = sentences.find((s) => s.ordinal === current);
  const previous =
    current === null
      ? undefined
      : sentences.findLast(
          (s) => s.ordinal < current && s.audio_path && s.guard_status === "passed",
        );
  const next = current === null ? undefined : nextPlayable(sentences, current);

  return (
    <section
      aria-label="Listen to the explanation"
      className="guilloche on-night fixed inset-x-2 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 flex items-center gap-2 rounded-2xl p-2 text-white shadow-float sm:gap-1 lg:sticky lg:inset-x-auto lg:bottom-4 lg:mt-6"
    >
      <audio
        ref={audioRef}
        onPlay={() => narration.setPlaying(true)}
        onPause={() => narration.setPlaying(false)}
        onEnded={() => {
          if (current !== null) narration.playNext(current);
        }}
        onError={() => narration.setFailed(true)}
      />

      <button
        type="button"
        aria-label="Previous sentence"
        disabled={!previous}
        onClick={() => previous && narration.play(previous)}
        className={NIGHT_ICON_BUTTON}
      >
        <SkipBack aria-hidden className="size-5" />
      </button>
      <button
        type="button"
        disabled={!ready}
        aria-label={playing ? "Pause" : current !== null ? "Resume" : "Play"}
        onClick={() => {
          const audio = audioRef.current;
          if (playing) audio?.pause();
          else if (current !== null && audio?.src) audio.play().catch(() => narration.setFailed(true));
          else narration.playNext(-1);
        }}
        className="flex size-13 shrink-0 items-center justify-center rounded-full bg-highlight text-ink transition-colors hover:bg-white disabled:bg-white/20 disabled:text-white"
      >
        {playing ? (
          <Pause aria-hidden className="size-6 fill-current" />
        ) : (
          <Play aria-hidden className="ml-0.5 size-6 fill-current" />
        )}
      </button>
      <button
        type="button"
        aria-label="Next sentence"
        disabled={!next}
        onClick={() => next && narration.play(next)}
        className={NIGHT_ICON_BUTTON}
      >
        <SkipForward aria-hidden className="size-5" />
      </button>

      <div className="min-w-0 flex-1 px-1 sm:px-2">
        {failed ? (
          <p role="alert" className="flex items-center gap-1.5 text-sm">
            <TriangleAlert aria-hidden className="size-4 shrink-0 text-highlight" />
            We couldn&apos;t play this audio. You can read it instead.
          </p>
        ) : finished && !ready ? (
          <p className="text-sm">Audio isn&apos;t available right now, so please read it instead.</p>
        ) : !ready ? (
          <p role="status" className="truncate text-sm">
            Preparing {preparing > 0 ? `${preparing} ${preparing === 1 ? "sentence" : "sentences"}` : "the audio"}…
          </p>
        ) : (
          <p
            lang={speaking && !english ? language : undefined}
            className="truncate leading-snug font-medium"
          >
            {speaking ? sentenceText(speaking, english) : <span lang={language}>{words.listen}</span>}
          </p>
        )}
        <div aria-hidden className="mt-1.5 flex gap-0.5">
          {sentences.map((s) => (
            <span
              key={s.id}
              className={`h-1 flex-1 rounded-full ${
                current !== null && s.ordinal < current
                  ? "bg-highlight/70"
                  : s.ordinal === current
                    ? "bg-highlight"
                    : "bg-white/25"
              }`}
            />
          ))}
        </div>
      </div>

      <button
        type="button"
        aria-label={`Playback speed ${speed} times. Change speed`}
        onClick={narration.cycleSpeed}
        className="min-h-11 min-w-12 shrink-0 rounded-lg px-1 text-sm font-semibold hover:bg-white/15"
      >
        {speed}×
      </button>
    </section>
  );
}

function SpeakingBars() {
  return (
    <span aria-hidden className="speaking-bars">
      <i />
      <i />
      <i />
    </span>
  );
}

export function Transcript({
  narration,
  sentences,
  claims,
  language,
  selectedClauseId,
  onShowSource,
}: {
  narration: Narration;
  sentences: Sentence[];
  claims: Claim[];
  language?: string;
  selectedClauseId?: string;
  onShowSource: (source: ClauseRef) => void;
}) {
  const { current, playing, english } = narration;
  const words = languageOf(language);
  const speakingRef = useRef<HTMLLIElement>(null);

  // Keep the voice's place in view, but only while this tab is the one showing.
  useEffect(() => {
    const row = speakingRef.current;
    if (!row || !row.offsetParent) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    row.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
  }, [current]);

  const sourceOf = (sentence: Sentence): ClauseRef | undefined =>
    claims.find((c) => sentence.claim_ids.includes(c.id))?.clauses[0];

  return (
    <section aria-labelledby="audio-heading">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div>
          <h2 id="audio-heading" lang={language} className="section-title">
            {words.explainedHeading}
          </h2>
          <p className="text-sm text-muted">Tap a sentence to hear it.</p>
        </div>
        <div
          role="group"
          aria-label="Language of the text"
          className="grid grid-cols-2 gap-0.5 rounded-lg bg-sunken p-0.5 text-sm"
        >
          {[
            { on: false, label: words.label, lang: language },
            { on: true, label: "English", lang: "en" },
          ].map((option) => (
            <button
              key={option.label}
              type="button"
              lang={option.lang}
              aria-pressed={english === option.on}
              onClick={() => narration.setEnglish(option.on)}
              className={`min-h-11 rounded-md px-3 font-medium ${
                english === option.on ? "bg-surface text-accent shadow-sm" : "text-muted hover:text-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <ol className="card mt-3 divide-y divide-line overflow-hidden">
        {sentences
          .filter((s) => s.guard_status !== "pending")
          .map((sentence) => {
            const flagged = sentence.guard_status === "flagged";
            const speaking = current === sentence.ordinal;
            const showEnglish = english || flagged || !sentence.translated_text;
            const sourced = claims
              .filter((c) => sentence.claim_ids.includes(c.id))
              .some((c) => c.clauses.some((clause) => clause.id === selectedClauseId));
            const source = sourceOf(sentence);
            return (
              <li
                key={sentence.id}
                ref={speaking ? speakingRef : undefined}
                className={`scroll-mt-32 scroll-mb-44 lg:scroll-mb-28 ${
                  speaking
                    ? "bg-highlight-soft shadow-[inset_4px_0_0_var(--color-highlight-strong)]"
                    : sourced
                      ? "bg-highlight-soft/50"
                      : ""
                }`}
              >
                <button
                  type="button"
                  aria-current={speaking ? "true" : undefined}
                  onClick={() => {
                    if (sentence.audio_path) narration.play(sentence);
                    else if (source) onShowSource(source);
                  }}
                  className="block w-full px-4 pt-3 pb-0.5 text-left text-lg leading-relaxed break-words transition-colors hover:bg-sunken/50"
                >
                  <span lang={showEnglish ? "en" : language}>
                    {showEnglish ? sentence.source_text : sentence.translated_text}
                  </span>
                  {flagged && (
                    <span className="mt-1 block text-sm font-medium text-warning">
                      We couldn&apos;t confirm the translation of this sentence,
                      so it&apos;s shown in English and not read aloud.
                    </span>
                  )}
                </button>
                <div className="flex items-center gap-3 px-4 pb-1">
                  {source && (
                    <SourceChip page={source.page} onClick={() => onShowSource(source)} />
                  )}
                  {speaking && playing && <SpeakingBars />}
                </div>
              </li>
            );
          })}
      </ol>
    </section>
  );
}
