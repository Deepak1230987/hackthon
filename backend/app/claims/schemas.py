from typing import Literal

from pydantic import BaseModel, Field

ClaimField = Literal[
    "benefit", "eligibility", "document", "deadline", "authority", "obligation", "penalty"
]
CLAIM_FIELDS: tuple[str, ...] = ClaimField.__args__
EntailmentLabel = Literal["ENTAILED", "PARTIAL", "NOT_ENTAILED"]


class TriageResult(BaseModel):
    is_policy: bool
    reason: str
    title: str | None = None
    issuing_authority: str | None = None
    issue_date: str | None = None  # YYYY-MM-DD


class CandidateClaim(BaseModel):
    field: ClaimField
    text: str = Field(max_length=300)  # one atomic fact in plain English
    clause_ordinals: list[int] = Field(min_length=1, max_length=3)
    quote: str = Field(max_length=500)  # verbatim, in the source language


class ExtractionResult(BaseModel):
    claims: list[CandidateClaim]


class RepairedClaim(BaseModel):
    index: int
    text: str = Field(max_length=300)
    clause_ordinals: list[int] = Field(min_length=1, max_length=3)
    quote: str = Field(max_length=500)


class RepairResult(BaseModel):
    claims: list[RepairedClaim]


class EntailmentVerdict(BaseModel):
    index: int
    label: EntailmentLabel


class EntailmentResult(BaseModel):
    verdicts: list[EntailmentVerdict]
