import json

import httpx
import pytest
from pydantic import BaseModel

from app.claims.schemas import ExtractionResult, TriageResult
from app.config import Settings
from app.providers.budget import BudgetExhausted
from app.providers.circuit import MAX_FAILURES, OPEN_S, WINDOW_S, Circuit
from app.providers.gateway import Gateway, ProviderUnavailable, gemini_schema


class Answer(BaseModel):
    value: int


class FakeBudget:
    def __init__(self, limit=100):
        self.calls = 0
        self.limit = limit
        self.failovers = []

    async def charge(self):
        self.calls += 1
        if self.calls > self.limit:
            raise BudgetExhausted("used")

    async def failover(self, source, target, reason):
        self.failovers.append((source, target, reason))


def gemini_reply(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def openai_reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def make(gemini, openai=None, monkeypatch=None):
    config = {"openai_api_key": "o", "llm_fallback_model": "backup"} if openai else {}
    gateway = Gateway(
        Settings(_env_file=None, database_url="postgresql://x", llm_primary_model="main", **config)
    )
    gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(gemini))
    if openai:
        gateway._openai = httpx.AsyncClient(transport=httpx.MockTransport(openai))
    return gateway


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instantly(_):
        return None

    monkeypatch.setattr("app.providers.gateway.asyncio.sleep", instantly)


async def test_returns_validated_reply_and_charges_once():
    budget = FakeBudget()
    result = await make(lambda r: gemini_reply('{"value": 3}')).structured("t", "p", Answer, budget)
    assert result.value == 3
    assert budget.calls == 1


async def test_triage_uses_the_fast_model_and_other_tasks_do_not():
    used = []

    def gemini(request):
        used.append(request.url.path.rsplit("/", 1)[1].split(":")[0])
        return gemini_reply('{"value": 1}')

    gateway = make(gemini)
    gateway._settings.llm_fast_model = "quick"
    await gateway.structured("triage", "p", Answer, FakeBudget())
    await gateway.structured("extract", "p", Answer, FakeBudget())
    assert used == ["quick", "main"]


async def test_bad_reply_gets_one_repair_with_the_error():
    seen = []

    def gemini(request):
        seen.append(json.loads(request.content)["contents"][0]["parts"][0]["text"])
        return gemini_reply('{"value": "nope"}' if len(seen) == 1 else '{"value": 4}')

    budget = FakeBudget()
    result = await make(gemini).structured("t", "p", Answer, budget)
    assert result.value == 4
    assert budget.calls == 2
    assert "failed validation" in seen[1] and "nope" in seen[1]


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_failures_retry_then_fail_over_and_the_trace_is_told(status):
    budget = FakeBudget()
    calls = []

    def gemini(request):
        calls.append(1)
        return httpx.Response(status)

    result = await make(gemini, lambda r: openai_reply('{"value": 5}')).structured("t", "p", Answer, budget)
    assert result.value == 5
    assert len(calls) == 4
    assert budget.failovers == [("gemini", "openai", f"status {status}")]


async def test_timeout_fails_over():
    def gemini(request):
        raise httpx.ReadTimeout("slow")

    budget = FakeBudget()
    result = await make(gemini, lambda r: openai_reply('{"value": 6}')).structured("t", "p", Answer, budget)
    assert result.value == 6
    assert budget.failovers[0][2] == "ReadTimeout"


async def test_unfixable_reply_fails_over():
    budget = FakeBudget()
    result = await make(lambda r: gemini_reply("not json"), lambda r: openai_reply('{"value": 7}')).structured(
        "t", "p", Answer, budget
    )
    assert result.value == 7
    assert budget.calls == 3


@pytest.mark.parametrize(
    "body",
    [
        {"candidates": [{"finishReason": "SAFETY"}]},
        {"candidates": [{"finishReason": "RECITATION"}]},
        {"promptFeedback": {"blockReason": "SAFETY"}},
    ],
)
async def test_blocked_reply_fails_over(body):
    budget = FakeBudget()
    result = await make(
        lambda r: httpx.Response(200, json=body), lambda r: openai_reply('{"value": 8}')
    ).structured("t", "p", Answer, budget)
    assert result.value == 8
    assert budget.failovers[0][2].startswith("blocked")


async def test_all_providers_failing_is_reported():
    with pytest.raises(ProviderUnavailable):
        await make(lambda r: httpx.Response(503), lambda r: httpx.Response(503)).structured(
            "t", "p", Answer, FakeBudget()
        )


async def test_no_openai_key_means_no_failover():
    budget = FakeBudget()
    with pytest.raises(ProviderUnavailable):
        await make(lambda r: httpx.Response(503)).structured("t", "p", Answer, budget)
    assert budget.failovers == []


async def test_budget_exhaustion_stops_before_calling():
    calls = []

    def gemini(request):
        calls.append(1)
        return gemini_reply('{"value": 1}')

    with pytest.raises(BudgetExhausted):
        await make(gemini).structured("t", "p", Answer, FakeBudget(limit=0))
    assert calls == []


async def test_daily_quota_does_not_wait():
    calls = []

    def gemini(request):
        calls.append(1)
        detail = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "22000s"}
        return httpx.Response(429, json={"error": {"details": [detail]}})

    with pytest.raises(ProviderUnavailable):
        await make(gemini).structured("t", "p", Answer, FakeBudget())
    assert len(calls) == 1


async def test_open_circuit_skips_the_primary():
    calls = []

    def gemini(request):
        calls.append(1)
        return httpx.Response(400)

    gateway = make(gemini, lambda r: openai_reply('{"value": 9}'))
    for _ in range(MAX_FAILURES):
        await gateway.structured("t", "p", Answer, FakeBudget())
    calls.clear()
    budget = FakeBudget()
    assert (await gateway.structured("t", "p", Answer, budget)).value == 9
    assert calls == []
    assert budget.failovers[0][2] == "status 400" or budget.failovers[0][2] == "circuit open"


def test_circuit_opens_after_repeated_failures_and_recovers():
    now = [0.0]
    circuit = Circuit(clock=lambda: now[0])
    for _ in range(MAX_FAILURES - 1):
        circuit.record_failure()
    assert not circuit.is_open()
    circuit.record_failure()
    assert circuit.is_open()
    now[0] += OPEN_S + 1
    assert not circuit.is_open()


def test_circuit_forgets_old_failures():
    now = [0.0]
    circuit = Circuit(clock=lambda: now[0])
    for _ in range(MAX_FAILURES - 1):
        circuit.record_failure()
    now[0] += WINDOW_S + 1
    circuit.record_failure()
    assert not circuit.is_open()


def test_gemini_schema_flattens_references_and_nullable():
    schema = gemini_schema(ExtractionResult.model_json_schema())
    item = schema["properties"]["claims"]["items"]
    assert item["type"] == "OBJECT"
    assert "eligibility" in item["properties"]["field"]["enum"]
    assert item["properties"]["clause_ordinals"]["items"]["type"] == "INTEGER"
    triage = gemini_schema(TriageResult.model_json_schema())
    assert triage["properties"]["title"] == {"type": "STRING", "nullable": True}
    assert "$ref" not in json.dumps(schema)
