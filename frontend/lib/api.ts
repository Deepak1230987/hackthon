import type {
  ApiError,
  DocumentClauses,
  DocumentView,
  ParsedSpeech,
  RunSnapshot,
} from "./types";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export const MAX_PDF_MB = 50;

export class ApiRequestError extends Error {
  readonly error: ApiError;
  readonly httpStatus?: number;

  constructor(error: ApiError, httpStatus?: number) {
    super(error.message);
    this.error = error;
    this.httpStatus = httpStatus;
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiRequestError({
      code: "NETWORK",
      message: "We couldn't reach Haq. Check your connection and try again.",
      action: "retry",
    });
  }
  if (response.ok) return response;

  const body = await response.json().catch(() => null);
  throw new ApiRequestError(
    body?.error ?? {
      code: response.status === 413 ? "FILE_TOO_LARGE" : "SERVER_ERROR",
      message:
        response.status === 413
          ? `This file is larger than ${MAX_PDF_MB} MB. Upload a smaller file.`
          : "Something went wrong on our side. Please try again.",
      action: "retry",
    },
    response.status,
  );
}

export async function uploadDocument(
  file: File,
  language: string,
): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  form.append("language", language);
  const response = await request("/v1/documents", {
    method: "POST",
    body: form,
  });
  const { run_id } = (await response.json()) as { run_id: string };
  return run_id;
}

export async function submitUrl(
  url: string,
  language: string,
): Promise<string> {
  const response = await request("/v1/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, language }),
  });
  const { run_id } = (await response.json()) as { run_id: string };
  return run_id;
}

export async function fetchLibrary(): Promise<DocumentView[]> {
  const response = await request("/v1/library", { cache: "no-store" });
  const { documents } = (await response.json()) as {
    documents: DocumentView[];
  };
  return documents;
}

export async function startLibraryRun(
  documentId: string,
  language: string,
): Promise<string> {
  const response = await request(
    `/v1/library/${encodeURIComponent(documentId)}/runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language }),
    },
  );
  const { run_id } = (await response.json()) as { run_id: string };
  return run_id;
}

export async function fetchClauses(
  documentId: string,
): Promise<DocumentClauses> {
  const response = await request(
    `/v1/documents/${encodeURIComponent(documentId)}/clauses`,
    { cache: "no-store" },
  );
  return (await response.json()) as DocumentClauses;
}

export async function submitAnswer(
  runId: string,
  field: string,
  value: unknown,
): Promise<void> {
  await request(`/v1/runs/${encodeURIComponent(runId)}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers: { [field]: value } }),
  });
}

export async function skipQuestion(runId: string, field: string): Promise<void> {
  await request(`/v1/runs/${encodeURIComponent(runId)}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skip: [field] }),
  });
}

export async function speechToAnswer(
  runId: string,
  field: string,
  audio: Blob,
): Promise<ParsedSpeech> {
  const form = new FormData();
  form.append("audio", audio, "answer");
  form.append("field", field);
  const response = await request(
    `/v1/runs/${encodeURIComponent(runId)}/stt`,
    { method: "POST", body: form },
  );
  return (await response.json()) as ParsedSpeech;
}

// audio_path is "audio/{hash}.mp3".
export function audioUrl(audioPath: string): string {
  return `${API_URL}/v1/${audioPath}`;
}

export function documentFileUrl(documentId: string): string {
  return `${API_URL}/v1/documents/${encodeURIComponent(documentId)}/file`;
}

export async function fetchRun(runId: string): Promise<RunSnapshot> {
  const response = await request(`/v1/runs/${encodeURIComponent(runId)}`, {
    cache: "no-store",
  });
  return (await response.json()) as RunSnapshot;
}

export function runEventsUrl(runId: string): string {
  return `${API_URL}/v1/runs/${encodeURIComponent(runId)}/events`;
}
