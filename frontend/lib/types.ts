// Wire contract with the backend. See docs/LLD.md sections 12.2, 12.3 and 12.5.

export type RunStatus =
  | "queued"
  | "running"
  | "waiting_input"
  | "completed"
  | "partial"
  | "failed";

export type NodeName =
  | "acquire"
  | "parse"
  | "segment"
  | "triage"
  | "extract"
  | "verify"
  | "compile_rules"
  | "evaluate"
  | "script"
  | "translate"
  | "guard"
  | "tts";

export type ApiError = {
  code: string;
  message: string;
  action?: string;
  details?: Record<string, unknown>;
};

// EventSource only delivers named events it subscribes to, so every type the
// backend emits must be listed here.
export const RUN_EVENT_TYPES = [
  "run_status",
  "node_started",
  "node_finished",
  "fetch_attempt",
  "page_ocr",
  "segment_done",
  "triage_result",
  "claim_extracted",
  "claim_verified",
  "claim_rejected",
  "retry",
  "rules_compiled",
  "needs_input",
  "verdict",
  "script_ready",
  "sentence_translated",
  "failover",
  "guard_failed",
  "sentence_ready",
] as const;

export type RunEventType = (typeof RUN_EVENT_TYPES)[number];

export type RunEvent = {
  seq: number;
  type: RunEventType;
  payload: Record<string, unknown>;
};

export type DocumentView = {
  id: string;
  title?: string | null;
  source_url?: string | null;
  fetch_method: "http" | "browser" | "upload";
  fetched_at: string;
  sha256: string;
  issue_date?: string | null;
  page_count: number;
};

// GET /v1/runs/{id}
export type RunSnapshot = {
  id: string;
  status: RunStatus;
  document?: DocumentView | null;
  error?: ApiError | null;
  events: RunEvent[];
};

export type StepStatus = "running" | "done" | "failed" | "interrupted";

export type Step = {
  id: number;
  node: string;
  attempt: number;
  status: StepStatus;
  durationMs?: number;
  implemented?: boolean;
  events: RunEvent[];
};

export type RunView = {
  status: RunStatus;
  document?: DocumentView;
  steps: Step[];
  error?: ApiError;
};

export type ConnectionState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "polling"
  | "closed";
