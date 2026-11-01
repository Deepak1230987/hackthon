from typing import Any, NotRequired, TypedDict


class SourceRequest(TypedDict):
    upload_path: NotRequired[str]
    sha256: NotRequired[str]
    url: NotRequired[str]
    document_id: NotRequired[str]
    page_from: NotRequired[int]
    page_to: NotRequired[int]


class RunState(TypedDict):
    run_id: str
    language: str
    source: SourceRequest
    document_id: str | None
    claim_ids: list[str]
    verify_attempts: dict[str, int]
    guard_attempts: dict[str, int]
    pending_fields: list[str]  # field names only
    verdict: dict[str, Any] | None  # outcomes only, never input values
    sentence_ids: list[str]
    partial: bool


def initial_state(run_id: str, language: str, source: SourceRequest) -> RunState:
    return {
        "run_id": run_id,
        "language": language,
        "source": source,
        "document_id": None,
        "claim_ids": [],
        "verify_attempts": {},
        "guard_attempts": {},
        "pending_fields": [],
        "verdict": None,
        "sentence_ids": [],
        "partial": False,
    }
