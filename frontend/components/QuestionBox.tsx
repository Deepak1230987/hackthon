"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiRequestError, askQuestion, audioUrl, questionFromSpeech } from "@/lib/api";
import { languageOf } from "@/lib/languages";
import type { ClauseRef, QaAnswer } from "@/lib/types";

const MAX_QUESTION_CHARS = 500;
const MAX_RECORDING_MS = 30_000;
const BUTTON =
  "min-h-11 rounded-md border border-line bg-surface px-4 font-medium hover:border-accent disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-accent";
const PRIMARY =
  "min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-line disabled:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

type Asked = QaAnswer & { id: number; question: string };

function message(e: unknown): string {
  return e instanceof ApiRequestError ? e.message : "Something went wrong. Please try again.";
}

function recorderType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
}

function AnswerCard({
  asked,
  onShowSource,
}: {
  asked: Asked;
  onShowSource: (source: ClauseRef) => void;
}) {
  return (
    <li className="rounded-md border border-line bg-surface p-3">
      <p className="text-sm text-muted">{asked.question}</p>
      <p lang={asked.language} className="mt-1 font-medium">
        {asked.answer}
      </p>
      {asked.language !== "en" && (
        <p className="text-sm text-muted">{asked.answer_en}</p>
      )}
      {asked.abstained && (
        <p className="mt-1 text-sm text-muted">
          {asked.authority
            ? `You can ask ${asked.authority}, which issued it.`
            : "You can ask the office that issued it."}
        </p>
      )}
      {asked.audio_path && (
        <audio
          controls
          preload="none"
          src={audioUrl(asked.audio_path)}
          aria-label="Listen to this answer"
          className="mt-2 w-full"
        />
      )}
      {asked.citations.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-x-4">
          {asked.citations.map((source) => (
            <button
              key={source.id}
              type="button"
              onClick={() => onShowSource(source)}
              className="min-h-11 text-left text-sm font-medium text-accent underline focus-visible:outline-2 focus-visible:outline-accent"
            >
              See the source on page {source.page}
            </button>
          ))}
        </div>
      )}
    </li>
  );
}

export function QuestionBox({
  runId,
  language,
  onShowSource,
}: {
  runId: string;
  language?: string;
  onShowSource: (source: ClauseRef) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<Asked[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [recording, setRecording] = useState(false);
  const [listening, setListening] = useState(false);
  // Decided after mounting, because the server has no MediaRecorder.
  const [micType, setMicType] = useState<string | undefined>();
  const recorderRef = useRef<MediaRecorder | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setMicType(recorderType()), 0);
    return () => {
      clearTimeout(id);
      clearTimeout(stopTimerRef.current);
      const recorder = recorderRef.current;
      if (recorder?.state === "recording") recorder.stop();
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const asked = question.trim();
    if (!asked || asking) return;
    setAsking(true);
    setError(null);
    try {
      const reply = await askQuestion(runId, asked);
      setAnswers((known) => [{ ...reply, id: known.length, question: asked }, ...known]);
      setQuestion("");
    } catch (err) {
      setError(message(err));
    } finally {
      setAsking(false);
    }
  };

  const understand = async (audio: Blob) => {
    setListening(true);
    setError(null);
    try {
      const transcript = await questionFromSpeech(runId, audio);
      if (transcript) {
        // Left in the box, so they can check and correct it before asking.
        setQuestion(transcript.slice(0, MAX_QUESTION_CHARS));
        inputRef.current?.focus();
      } else {
        setError("We couldn't hear that clearly. Say it again, or type it.");
      }
    } catch (err) {
      setError(message(err));
    } finally {
      setListening(false);
    }
  };

  const startRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: micType });
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        clearTimeout(stopTimerRef.current);
        setRecording(false);
        void understand(new Blob(chunks, { type: micType }));
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      stopTimerRef.current = setTimeout(() => recorder.stop(), MAX_RECORDING_MS);
    } catch {
      // Permission refused or no microphone. Typing still works, so it isn't a dead end.
      setMicType(undefined);
      setError("We can't use your microphone. Please type your question.");
    }
  };

  const busy = asking || listening || recording;

  return (
    <section aria-labelledby="ask-heading" className="rounded-lg border border-line bg-surface p-4">
      <h2 id="ask-heading" lang={language} className="text-lg font-semibold">
        {languageOf(language).askHeading}
      </h2>
      <p className="text-sm text-muted">
        Ask about this document. If it doesn&apos;t say, we&apos;ll tell you. Please leave out
        personal details. Questions aren&apos;t saved.
      </p>

      <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-2">
        <textarea
          ref={inputRef}
          aria-label="Your question"
          rows={2}
          maxLength={MAX_QUESTION_CHARS}
          value={question}
          lang={language}
          onChange={(e) => setQuestion(e.target.value)}
          className="w-full rounded-md border border-line bg-paper px-3 py-2 focus-visible:outline-2 focus-visible:outline-accent"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" disabled={busy || !question.trim()} className={PRIMARY}>
            {asking ? "Checking the document…" : "Ask"}
          </button>
          {micType && !recording && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void startRecording()}
              className={BUTTON}
            >
              {listening ? "Listening…" : "Ask by voice"}
            </button>
          )}
          {recording && (
            <button
              type="button"
              onClick={() => recorderRef.current?.stop()}
              className={PRIMARY}
            >
              Stop recording
            </button>
          )}
        </div>
      </form>

      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}

      <ul aria-live="polite" className="mt-3 flex flex-col gap-2 empty:hidden">
        {answers.map((asked) => (
          <AnswerCard key={asked.id} asked={asked} onShowSource={onShowSource} />
        ))}
      </ul>
    </section>
  );
}
