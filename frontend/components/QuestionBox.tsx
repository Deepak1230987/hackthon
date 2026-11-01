"use client";

import { Lock, Mic, SendHorizontal, Square } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { SourceChip, Spinner } from "@/components/ui";
import { ApiRequestError, askQuestion, audioUrl, questionFromSpeech } from "@/lib/api";
import { languageOf } from "@/lib/languages";
import type { ClauseRef, QaAnswer } from "@/lib/types";

const MAX_QUESTION_CHARS = 500;
const MAX_RECORDING_MS = 30_000;

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
    <li className="flex flex-col gap-2">
      <p
        lang={asked.language}
        className="max-w-[85%] self-end rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-white"
      >
        {asked.question}
      </p>
      <div className="card rounded-bl-md p-4">
        <p lang={asked.language} className="text-lg leading-relaxed font-medium">
          {asked.answer}
        </p>
        {asked.language !== "en" && (
          <p className="mt-1 text-sm text-muted">{asked.answer_en}</p>
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
            className="mt-3 h-11 w-full"
          />
        )}
        {asked.citations.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-x-2">
            {asked.citations.map((source) => (
              <SourceChip key={source.id} page={source.page} onClick={() => onShowSource(source)} />
            ))}
          </div>
        )}
      </div>
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
  const words = languageOf(language);
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

  const ask = async (text: string) => {
    const asked = text.trim();
    if (!asked || asking) return;
    setAsking(true);
    setError(null);
    setQuestion(asked);
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

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // While an input method is composing Devanagari, Enter picks a word and doesn't send.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void ask(question);
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
    <section aria-labelledby="ask-heading">
      <h2 id="ask-heading" lang={language} className="section-title">
        {words.askHeading}
      </h2>
      <p className="mt-1 flex gap-2 text-sm text-muted">
        <Lock aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span>
          Ask about this document. If it doesn&apos;t say, we&apos;ll tell you. Please leave out
          personal details. Questions aren&apos;t saved.
        </span>
      </p>

      <form onSubmit={onSubmit} className="card mt-3 p-2">
        <textarea
          ref={inputRef}
          aria-label="Your question"
          rows={2}
          maxLength={MAX_QUESTION_CHARS}
          value={question}
          lang={language}
          enterKeyHint="send"
          placeholder={words.askHeading}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          className="w-full resize-none rounded-lg px-2 py-1.5 text-lg outline-none"
        />
        <div className="flex items-center gap-2">
          {micType && !recording && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void startRecording()}
              className="btn btn-secondary"
            >
              {listening ? <Spinner /> : <Mic aria-hidden className="size-5 text-accent" />}
              {listening ? "Listening…" : "Ask by voice"}
            </button>
          )}
          {recording && (
            <button
              type="button"
              onClick={() => recorderRef.current?.stop()}
              className="btn btn-primary"
            >
              <Square aria-hidden className="size-4 fill-current" />
              Stop recording
            </button>
          )}
          <button type="submit" disabled={busy || !question.trim()} className="btn btn-primary ml-auto">
            {asking ? <Spinner /> : <SendHorizontal aria-hidden className="size-5" />}
            {asking ? "Checking the document…" : "Ask"}
          </button>
        </div>
      </form>

      {answers.length === 0 && (
        <ul aria-label="Questions you could ask" className="mt-3 flex flex-wrap gap-2">
          {words.suggestions.map((suggestion) => (
            <li key={suggestion}>
              <button
                type="button"
                lang={language}
                disabled={busy}
                onClick={() => void ask(suggestion)}
                className="min-h-11 rounded-full border border-line-strong bg-surface px-4 transition-colors hover:border-accent hover:text-accent disabled:opacity-60"
              >
                {suggestion}
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}

      <ul aria-live="polite" className="mt-5 flex flex-col gap-5 empty:hidden">
        {answers.map((asked) => (
          <AnswerCard key={asked.id} asked={asked} onShowSource={onShowSource} />
        ))}
      </ul>
    </section>
  );
}
