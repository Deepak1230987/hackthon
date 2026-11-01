"use client";

import {
  Check,
  CircleCheck,
  CircleHelp,
  CircleX,
  ChevronRight,
  Lock,
  Mic,
  Square,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Spinner } from "@/components/ui";
import { ApiRequestError, skipQuestion, speechToAnswer, submitAnswer } from "@/lib/api";
import { languageOf } from "@/lib/languages";
import { answerLabel, optionLabel, questionText, typedValue, unitLabel } from "@/lib/questions";
import type { Claim, ClauseRef, Question, Verdict } from "@/lib/types";

const MAX_RECORDING_MS = 30_000;
const ANSWER =
  "btn btn-secondary min-h-14 text-lg";

const OUTCOMES: Record<
  string,
  { hi: string; mr: string; en: string; tone: string; iconTone: string; Icon: LucideIcon }
> = {
  MEETS_STATED_CRITERIA: {
    mr: "या दस्तऐवजात सांगितलेल्या अटी तुम्ही पूर्ण करत असल्याचे दिसते.",
    hi: "आप इस दस्तावेज़ की बताई गई शर्तें पूरी करते दिखते हैं।",
    en: "You appear to meet the criteria this document states.",
    tone: "border-success/40 bg-success-soft",
    iconTone: "text-success",
    Icon: CircleCheck,
  },
  DOES_NOT_MEET: {
    mr: "या दस्तऐवजातील किमान एक अट पूर्ण होत असल्याचे दिसत नाही.",
    hi: "इस दस्तावेज़ की कम से कम एक शर्त पूरी होती नहीं दिखती।",
    en: "You do not appear to meet at least one criterion in this document.",
    tone: "border-danger/40 bg-danger-soft",
    iconTone: "text-danger",
    Icon: CircleX,
  },
  NEEDS_INFO: {
    mr: "तुम्ही पात्र आहात की नाही हे सांगण्यासाठी आम्हाला आणखी माहिती हवी आहे.",
    hi: "यह बताने के लिए कि आप पात्र हैं या नहीं, हमें और जानकारी चाहिए।",
    en: "We need more details to tell whether you qualify.",
    tone: "border-warning/40 bg-warning-soft",
    iconTone: "text-warning",
    Icon: CircleHelp,
  },
  CANNOT_DETERMINE: {
    mr: "तुम्ही पात्र आहात की नाही हे आम्ही या दस्तऐवजावरून सांगू शकत नाही.",
    hi: "हम इस दस्तावेज़ से यह नहीं बता सकते कि आप पात्र हैं या नहीं।",
    en: "We cannot tell from this document whether you qualify.",
    tone: "border-warning/40 bg-warning-soft",
    iconTone: "text-warning",
    Icon: CircleHelp,
  },
};

function recorderType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
}

function message(e: unknown): string {
  return e instanceof ApiRequestError ? e.message : "Something went wrong. Please try again.";
}

function QuestionForm({
  runId,
  question,
  language,
}: {
  runId: string;
  question: Question;
  language: string;
}) {
  const words = languageOf(language);
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
  const questionRef = useRef<HTMLParagraphElement>(null);

  // Each question mounts this form afresh, and it can appear far from where someone has
  // scrolled. Not while the PDF is open over the page on a phone, which would lose their place.
  useEffect(() => {
    const element = questionRef.current;
    if (!element || document.querySelector('[role="dialog"]')) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
  }, []);

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
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
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
      <p role="status" className="mt-3 flex items-center gap-2.5 text-lg font-medium">
        <Spinner className="size-5 text-accent" />
        Thanks. Checking the rules…
      </p>
    );
  }

  const busy = saving || listening || recording;
  const unit = unitLabel(question, language);

  return (
    <div className="mt-1">
      <p
        ref={questionRef}
        tabIndex={-1}
        lang={language}
        className="font-display text-3xl leading-snug outline-none"
      >
        {questionText(question, language)}
      </p>
      <p className="mt-0.5 text-muted">{question.question_en}</p>

      {heard ? (
        <div className="mt-4 rounded-xl bg-highlight-soft p-4">
          <p className="text-sm text-muted">
            We heard: <span lang={language}>{heard.transcript}</span>
          </p>
          <p className="mt-1 text-lg font-semibold">
            Is this right?{" "}
            <span lang={language}>{answerLabel(question, heard.value, language)}</span>
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button type="button" disabled={saving} onClick={() => void send(heard.value)} className="btn btn-primary">
              <Check aria-hidden className="size-5" />
              Yes, that&apos;s right
            </button>
            <button type="button" disabled={saving} onClick={() => setHeard(null)} className="btn btn-secondary">
              No, try again
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {question.type === "bool" && (
            <div className="grid grid-cols-2 gap-2">
              <button type="button" disabled={busy} onClick={() => void send(true)} className={ANSWER}>
                <Check aria-hidden className="size-5 text-success" />
                <span>
                  <span lang={language}>{words.yes}</span> / Yes
                </span>
              </button>
              <button type="button" disabled={busy} onClick={() => void send(false)} className={ANSWER}>
                <X aria-hidden className="size-5 text-danger" />
                <span>
                  <span lang={language}>{words.no}</span> / No
                </span>
              </button>
            </div>
          )}

          {question.type === "enum" &&
            ((question.options ?? []).length > 12 ? (
              <select
                aria-label={question.question_en}
                disabled={busy}
                defaultValue=""
                onChange={(e) => e.target.value && void send(e.target.value)}
                className="field text-lg"
              >
                <option value="" disabled>
                  Choose
                </option>
                {question.options?.map((option) => (
                  <option key={option} value={option}>
                    {optionLabel(option, language)}
                  </option>
                ))}
              </select>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {question.options?.map((option) => (
                  <button
                    key={option}
                    type="button"
                    lang={language}
                    disabled={busy}
                    onClick={() => void send(option)}
                    className="btn btn-secondary min-h-13 px-2"
                  >
                    {optionLabel(option, language)}
                  </button>
                ))}
              </div>
            ))}

          {question.type !== "bool" && question.type !== "enum" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (typed.trim()) void send(typedValue(question, typed));
              }}
              className="flex gap-2"
            >
              <div className="relative min-w-0 flex-1">
                <input
                  aria-label={question.question_en}
                  inputMode={question.type === "str" ? "text" : "decimal"}
                  autoComplete="off"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  className={`field min-h-14 text-xl font-medium ${unit ? "pr-20" : ""}`}
                />
                {unit && (
                  <span
                    lang={language}
                    className="pointer-events-none absolute inset-y-0 right-3.5 flex items-center text-muted"
                  >
                    {unit}
                  </span>
                )}
              </div>
              <button
                type="submit"
                disabled={busy || !typed.trim()}
                className="btn btn-primary min-h-14 shrink-0"
              >
                Next
                <ChevronRight aria-hidden className="size-5" />
              </button>
            </form>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {micType && !recording && (
              <button type="button" disabled={busy} onClick={() => void startRecording()} className="btn btn-secondary">
                {listening ? <Spinner /> : <Mic aria-hidden className="size-5 text-accent" />}
                {listening ? "Listening to your answer…" : "Answer by voice"}
              </button>
            )}
            {recording && (
              <>
                <button type="button" onClick={() => recorderRef.current?.stop()} className="btn btn-primary">
                  <Square aria-hidden className="size-4 fill-current" />
                  Stop recording
                </button>
                <span role="status" className="flex items-center gap-2 text-sm font-medium text-danger">
                  <span aria-hidden className="size-2.5 animate-pulse rounded-full bg-danger motion-reduce:animate-none" />
                  Speak now, then tap stop.
                </span>
              </>
            )}
            <button type="button" disabled={busy} onClick={() => void skip()} className="btn btn-ghost">
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

const OPEN_LINKS = 3;

const LINK_ICONS: Record<string, { Icon: LucideIcon; tone: string }> = {
  failed: { Icon: X, tone: "text-danger" },
  met: { Icon: Check, tone: "text-success" },
  unknown: { Icon: CircleHelp, tone: "text-warning" },
};

function ClaimLinks({
  title,
  kind,
  ids,
  claims,
  onShowSource,
}: {
  title: string;
  kind: keyof typeof LINK_ICONS;
  ids: string[];
  claims: Claim[];
  onShowSource: (source: ClauseRef) => void;
}) {
  const found = ids
    .map((id) => claims.find((c) => c.id === id))
    .filter((c): c is Claim => Boolean(c?.clauses.length));
  if (found.length === 0) return null;
  const { Icon, tone } = LINK_ICONS[kind];
  const list = (items: Claim[]) => (
    <ul className="flex flex-col">
      {items.map((claim) => (
        <li key={claim.id}>
          <button
            type="button"
            onClick={() => onShowSource(claim.clauses[0])}
            className="group flex min-h-11 w-full items-center gap-2.5 rounded-lg py-1.5 text-left"
          >
            <Icon aria-hidden className={`size-5 shrink-0 ${tone}`} />
            <span className="min-w-0 flex-1 leading-snug group-hover:underline">{claim.text}</span>
            <span className="shrink-0 text-sm font-semibold text-accent">
              p.&nbsp;{claim.clauses[0].page}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="mt-3 border-t border-ink/10 pt-2">
      <h3 className="text-sm font-semibold">
        {title} <span className="font-normal text-muted">· {found.length}</span>
      </h3>
      {list(found.slice(0, OPEN_LINKS))}
      {found.length > OPEN_LINKS && (
        <details className="text-sm">
          <summary className="min-h-11 py-2 font-medium text-accent">
            Show {found.length - OPEN_LINKS} more
          </summary>
          {list(found.slice(OPEN_LINKS))}
        </details>
      )}
    </div>
  );
}

export function EligibilityPanel({
  runId,
  question,
  verdict,
  claims,
  language,
  onShowSource,
}: {
  runId: string;
  language: string;
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
        className="card overflow-hidden border-accent/40 shadow-[inset_0_4px_0_var(--color-accent)]"
      >
        <div className="p-4 pt-5 sm:p-6">
          <h2 id="eligibility-heading" className="eyebrow">
            Check if this applies to you
          </h2>
          <QuestionForm key={question.name} runId={runId} question={question} language={language} />
          <p className="mt-4 flex gap-2 text-sm text-muted">
            <Lock aria-hidden className="mt-0.5 size-4 shrink-0" />
            Your answers are used only for this check. They aren&apos;t saved, and
            a voice recording is never kept.
          </p>
        </div>
      </section>
    );
  }

  const outcome = OUTCOMES[verdict!.outcome] ?? OUTCOMES.CANNOT_DETERMINE;
  const { Icon } = outcome;
  return (
    <section
      aria-labelledby="eligibility-heading"
      className={`rounded-2xl border p-4 sm:p-5 ${outcome.tone}`}
    >
      <div className="flex gap-3">
        <Icon aria-hidden className={`mt-1 size-8 shrink-0 ${outcome.iconTone}`} />
        <div className="min-w-0">
          <h2 id="eligibility-heading" lang={language} className="font-display text-2xl leading-snug text-balance sm:text-3xl">
            {language === "mr" ? outcome.mr : outcome.hi}
          </h2>
          <p className="mt-0.5 text-muted">{outcome.en}</p>
        </div>
      </div>
      <ClaimLinks title="Not met" kind="failed" ids={verdict!.failed} claims={claims} onShowSource={onShowSource} />
      <ClaimLinks title="Met" kind="met" ids={verdict!.met} claims={claims} onShowSource={onShowSource} />
      <ClaimLinks title="Couldn't check" kind="unknown" ids={verdict!.unknown} claims={claims} onShowSource={onShowSource} />
    </section>
  );
}
