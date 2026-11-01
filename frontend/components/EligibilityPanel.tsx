"use client";

import { useEffect, useRef, useState } from "react";

import { ApiRequestError, skipQuestion, speechToAnswer, submitAnswer } from "@/lib/api";
import { answerLabel, optionLabel, questionText, typedValue } from "@/lib/questions";
import type { Claim, ClauseRef, Question, Verdict } from "@/lib/types";

const MAX_RECORDING_MS = 30_000;
const BUTTON =
  "min-h-11 rounded-md border border-line bg-surface px-4 font-medium hover:border-accent disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-accent";
const PRIMARY =
  "min-h-11 rounded-md bg-accent px-5 font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-line disabled:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const OUTCOMES: Record<string, { hi: string; en: string; tone: string }> = {
  MEETS_STATED_CRITERIA: {
    hi: "आप इस दस्तावेज़ की बताई गई शर्तें पूरी करते दिखते हैं।",
    en: "You appear to meet the criteria this document states.",
    tone: "border-success/40",
  },
  DOES_NOT_MEET: {
    hi: "इस दस्तावेज़ की कम से कम एक शर्त पूरी होती नहीं दिखती।",
    en: "You do not appear to meet at least one criterion in this document.",
    tone: "border-danger/40",
  },
  NEEDS_INFO: {
    hi: "यह बताने के लिए कि आप पात्र हैं या नहीं, हमें और जानकारी चाहिए।",
    en: "We need more details to tell whether you qualify.",
    tone: "border-warning/40",
  },
  CANNOT_DETERMINE: {
    hi: "हम इस दस्तावेज़ से यह नहीं बता सकते कि आप पात्र हैं या नहीं।",
    en: "We cannot tell from this document whether you qualify.",
    tone: "border-warning/40",
  },
};

function recorderType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
}

function message(e: unknown): string {
  return e instanceof ApiRequestError ? e.message : "Something went wrong. Please try again.";
}

function QuestionForm({ runId, question }: { runId: string; question: Question }) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [recording, setRecording] = useState(false);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState<{ transcript: string; value: unknown } | null>(null);
  // Decided after mounting, because the server has no MediaRecorder.
  const [micType, setMicType] = useState<string | undefined>();
  const recorderRef = useRef<MediaRecorder | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const id = setTimeout(() => setMicType(recorderType()), 0);
    return () => {
      clearTimeout(id);
      clearTimeout(stopTimerRef.current);
      const recorder = recorderRef.current;
      if (recorder?.state === "recording") recorder.stop();
    };
  }, []);

  const send = async (value: unknown) => {
    setSaving(true);
    setError(null);
    try {
      await submitAnswer(runId, question.name, value);
      setSaved(true);
    } catch (e) {
      setError(message(e));
      setHeard(null);
      setSaving(false);
    }
  };

  const skip = async () => {
    setSaving(true);
    setError(null);
    try {
      await skipQuestion(runId, question.name);
      setSaved(true);
    } catch (e) {
      setError(message(e));
      setSaving(false);
    }
  };

  const understand = async (audio: Blob) => {
    setListening(true);
    setError(null);
    try {
      const result = await speechToAnswer(runId, question.name, audio);
      if (result.parsed === null) {
        setError(
          result.transcript
            ? `We heard "${result.transcript}" but couldn't read an answer. Say it again, or type it.`
            : "We couldn't hear that clearly. Say it again, or type it.",
        );
      } else {
        setHeard({ transcript: result.transcript, value: result.parsed });
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setListening(false);
    }
  };

  const startRecording = async () => {
    setError(null);
    setHeard(null);
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
      setError("We can't use your microphone. Please type your answer.");
    }
  };

  if (saved) {
    return (
      <p role="status" className="mt-2 text-muted">
        Thanks. Checking the rules…
      </p>
    );
  }

  const busy = saving || listening || recording;

  return (
    <div className="mt-2">
      <p lang="hi" className="text-lg font-medium">
        {questionText(question)}
      </p>
      <p className="text-sm text-muted">{question.question_en}</p>

      {heard ? (
        <div className="mt-3 rounded-md border border-highlight-strong bg-highlight-soft p-3">
          <p className="text-sm text-muted">
            We heard: <span lang="hi">{heard.transcript}</span>
          </p>
          <p className="mt-1 font-semibold">
            Is this right? <span lang="hi">{answerLabel(question, heard.value)}</span>
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" disabled={saving} onClick={() => void send(heard.value)} className={PRIMARY}>
              Yes, that&apos;s right
            </button>
            <button type="button" disabled={saving} onClick={() => setHeard(null)} className={BUTTON}>
              No, try again
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          {question.type === "bool" && (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} onClick={() => void send(true)} className={BUTTON}>
                <span lang="hi">हाँ</span> / Yes
              </button>
              <button type="button" disabled={busy} onClick={() => void send(false)} className={BUTTON}>
                <span lang="hi">नहीं</span> / No
              </button>
            </div>
          )}

          {question.type === "enum" && (
            <div className="flex flex-wrap gap-2">
              {(question.options ?? []).length > 12 ? (
                <select
                  aria-label={question.question_en}
                  disabled={busy}
                  defaultValue=""
                  onChange={(e) => e.target.value && void send(e.target.value)}
                  className="min-h-11 w-full rounded-md border border-line bg-surface px-2"
                >
                  <option value="" disabled>
                    Choose
                  </option>
                  {question.options?.map((option) => (
                    <option key={option} value={option}>
                      {optionLabel(option)}
                    </option>
                  ))}
                </select>
              ) : (
                question.options?.map((option) => (
                  <button
                    key={option}
                    type="button"
                    lang="hi"
                    disabled={busy}
                    onClick={() => void send(option)}
                    className={BUTTON}
                  >
                    {optionLabel(option)}
                  </button>
                ))
              )}
            </div>
          )}

          {question.type !== "bool" && question.type !== "enum" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (typed.trim()) void send(typedValue(question, typed));
              }}
              className="flex flex-wrap gap-2"
            >
              <input
                aria-label={question.question_en}
                inputMode={question.type === "str" ? "text" : "decimal"}
                autoComplete="off"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                className="min-h-11 min-w-0 flex-1 rounded-md border border-line bg-surface px-3 focus-visible:outline-2 focus-visible:outline-accent"
              />
              <button type="submit" disabled={busy || !typed.trim()} className={PRIMARY}>
                Next
              </button>
            </form>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {micType && !recording && (
              <button type="button" disabled={busy} onClick={() => void startRecording()} className={BUTTON}>
                {listening ? "Listening to your answer…" : "Answer by voice"}
              </button>
            )}
            {recording && (
              <button type="button" onClick={() => recorderRef.current?.stop()} className={PRIMARY}>
                Stop recording
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => void skip()} className={BUTTON}>
              I don&apos;t know
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

function ClaimLinks({
  title,
  ids,
  claims,
  onShowSource,
}: {
  title: string;
  ids: string[];
  claims: Claim[];
  onShowSource: (source: ClauseRef) => void;
}) {
  const found = ids
    .map((id) => claims.find((c) => c.id === id))
    .filter((c): c is Claim => Boolean(c?.clauses.length));
  if (found.length === 0) return null;
  return (
    <div className="mt-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="mt-1 flex flex-col gap-1 text-sm">
        {found.map((claim) => (
          <li key={claim.id}>
            <button
              type="button"
              onClick={() => onShowSource(claim.clauses[0])}
              className="min-h-11 text-left underline focus-visible:outline-2 focus-visible:outline-accent"
            >
              {claim.text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EligibilityPanel({
  runId,
  question,
  verdict,
  claims,
  onShowSource,
}: {
  runId: string;
  question?: Question;
  verdict?: Verdict;
  claims: Claim[];
  onShowSource: (source: ClauseRef) => void;
}) {
  if (!question && !verdict) return null;

  if (question) {
    return (
      <section
        aria-labelledby="eligibility-heading"
        className="rounded-lg border border-accent bg-accent-soft p-4"
      >
        <h2 id="eligibility-heading" className="text-sm font-semibold text-accent">
          Check if this applies to you
        </h2>
        <QuestionForm key={question.name} runId={runId} question={question} />
        <p className="mt-3 text-xs text-muted">
          Your answers are used only for this check. They aren&apos;t saved, and
          a voice recording is never kept.
        </p>
      </section>
    );
  }

  const outcome = OUTCOMES[verdict!.outcome] ?? OUTCOMES.CANNOT_DETERMINE;
  return (
    <section
      aria-labelledby="eligibility-heading"
      className={`rounded-lg border-2 bg-surface p-4 ${outcome.tone}`}
    >
      <h2 id="eligibility-heading" lang="hi" className="text-lg font-semibold">
        {outcome.hi}
      </h2>
      <p className="text-sm text-muted">{outcome.en}</p>
      <ClaimLinks title="Not met" ids={verdict!.failed} claims={claims} onShowSource={onShowSource} />
      <ClaimLinks title="Met" ids={verdict!.met} claims={claims} onShowSource={onShowSource} />
      <ClaimLinks title="Couldn't check" ids={verdict!.unknown} claims={claims} onShowSource={onShowSource} />
    </section>
  );
}
