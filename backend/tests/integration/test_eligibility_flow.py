import asyncio
import json
import uuid

import pytest
from sqlalchemy import select, text

from app.claims.schemas import CandidateClaim, ExtractionResult
from app.db.models import Rule, Sentence
from app.graph.nodes.compile_rules import CompiledClaim, RulesResult
from app.graph.nodes.script import ScriptResult, ScriptSentence
from app.providers.gateway import ProviderUnavailable
from tests.conftest import make_pdf
from tests.integration.test_claims_flow import events_of, wait_for_end
from tests.integration.test_runs import upload

pytestmark = pytest.mark.integration

INCOME_TEXT = "Income must be below Rs. 2,50,000."
AGE_TEXT = "Applicants must be at least 18 years old."
DOCUMENT = "Annual income must be below Rs. 2,50,000. Applicants must be at least 18 years old."
# Distinctive, so it can be searched for in the checkpoint tables.
SECRET_INCOME = 123457


def claim(text, quote, field="eligibility"):
    return CandidateClaim(field=field, text=text, clause_ordinals=[1], quote=quote)


INCOME = claim(INCOME_TEXT, "income must be below Rs. 2,50,000")
AGE = claim(AGE_TEXT, "must be at least 18 years old")


def cmp(field, op, value):
    return json.dumps({"type": "cmp", "field": field, "op": op, "value": value})


INCOME_RULE = cmp("annual_income_inr", "lt", 250000)
AGE_RULE = cmp("age", "gte", 18)


async def stored_rules(app, run_id):
    async with app.state.services.deps.sessions() as session:
        return (await session.scalars(select(Rule).where(Rule.run_id == uuid.UUID(run_id)))).all()


async def stored_sentences(app, run_id):
    async with app.state.services.deps.sessions() as session:
        return (
            await session.scalars(
                select(Sentence).where(Sentence.run_id == uuid.UUID(run_id)).order_by(Sentence.ordinal)
            )
        ).all()


async def wait_for_question(client, run_id):
    for _ in range(400):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] == "waiting_input":
            return view
        assert view["status"] not in ("completed", "partial", "failed"), view
        await asyncio.sleep(0.05)
    raise AssertionError(f"Run never asked: {view}")


async def start(client, gateway, salt, claims=None, compiled=None):
    """Compiles to `compiled`, in the order the claims end up in, which is by random ID."""
    gateway.replies["extract"] = [ExtractionResult(claims=claims or [INCOME, AGE])]
    wanted = compiled if compiled is not None else {INCOME_TEXT: INCOME_RULE, AGE_TEXT: AGE_RULE}
    gateway.rule_texts = wanted
    return await upload(client, make_pdf(f"{DOCUMENT} {salt}"))


@pytest.fixture(autouse=True)
def answer_rules_by_claim_text(gateway, monkeypatch):
    """Rules are asked for by index, and indexes depend on random claim IDs."""
    structured = gateway.structured

    async def reply(task, prompt, schema, budget):
        if task != "rules" or gateway.replies.get("rules"):
            return await structured(task, prompt, schema, budget)
        await budget.charge()
        gateway.prompts.setdefault(task, []).append(prompt)
        rules = []
        for index, line in enumerate(l for l in prompt.splitlines() if l.startswith("<claim index=")):
            for claim_text, spec in gateway.rule_texts.items():
                if claim_text in line:
                    expr, group = spec if isinstance(spec, tuple) else (spec, None)
                    rules.append(CompiledClaim(index=index, expr=expr, alternative_group=group))
        return RulesResult(rules=rules)

    gateway.rule_texts = {}
    monkeypatch.setattr(gateway, "structured", reply)


async def test_run_pauses_asks_one_question_at_a_time_and_finishes(client, gateway, app):
    run_id = await start(client, gateway, "happy")
    view = await wait_for_question(client, run_id)
    first = view["question"]["name"]
    assert first in ("age", "annual_income_inr")
    assert view["question"]["question_en"]
    assert view["verdict"] is None
    assert [e["field"] for e in events_of(view, "needs_input")] == [first]
    assert events_of(view, "rules_compiled") == [{"count": 2}]

    answer = {"age": 30, "annual_income_inr": 100000}
    response = await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {first: answer[first]}})
    assert response.status_code == 200

    second = "age" if first != "age" else "annual_income_inr"
    for _ in range(400):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] == "waiting_input" and view["question"]["name"] == second:
            break
        await asyncio.sleep(0.05)
    assert view["question"]["name"] == second

    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {second: answer[second]}})
    view = await wait_for_end(client, run_id)
    assert view["status"] == "completed"
    assert view["question"] is None
    assert view["verdict"]["outcome"] == "MEETS_STATED_CRITERIA"
    assert len(view["verdict"]["met"]) == 2
    assert events_of(view, "verdict")[0]["outcome"] == "MEETS_STATED_CRITERIA"
    statuses = [e["status"] for e in events_of(view, "run_status")]
    assert statuses.count("waiting_input") == 2
    # Rules aren't compiled again on resume.
    assert len(gateway.prompts["rules"]) == 1


async def test_failed_rule_ends_questions_early_and_names_the_claim(client, gateway):
    run_id = await start(client, gateway, "fails", claims=[INCOME, AGE])
    view = await wait_for_question(client, run_id)
    bad = {"age": 10, "annual_income_inr": 900000}
    name = view["question"]["name"]
    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {name: bad[name]}})
    view = await wait_for_end(client, run_id)
    assert view["verdict"]["outcome"] == "DOES_NOT_MEET"
    assert len(view["verdict"]["failed"]) == 1
    assert len(events_of(view, "needs_input")) == 1


async def test_skipping_is_not_asked_again_and_cannot_determine(client, gateway):
    run_id = await start(client, gateway, "skip", claims=[AGE], compiled={AGE_TEXT: AGE_RULE})
    await wait_for_question(client, run_id)
    response = await client.post(f"/v1/runs/{run_id}/answers", json={"skip": ["age"]})
    assert response.status_code == 200
    view = await wait_for_end(client, run_id)
    assert view["verdict"]["outcome"] == "CANNOT_DETERMINE"
    assert len(events_of(view, "needs_input")) == 1


@pytest.mark.parametrize(
    "expr",
    [
        "not json at all",
        '{"type":"cmp","field":"caste_code","op":"eq","value":"x"}',
        '{"type":"and","items":[]}',
        cmp("annual_income_inr", "lt", 999999),
    ],
)
async def test_bad_compile_becomes_unevaluable_and_never_decides(client, gateway, app, expr):
    run_id = await start(
        client, gateway, f"bad {expr}", claims=[INCOME], compiled={INCOME_TEXT: expr}
    )
    view = await wait_for_end(client, run_id)
    assert view["status"] == "completed"
    assert view["verdict"]["outcome"] == "CANNOT_DETERMINE"
    rules = await stored_rules(app, run_id)
    assert [r.ast["type"] for r in rules] == ["unevaluable"]
    assert rules[0].ast["source_text"] == INCOME_TEXT


async def test_alternatives_pass_on_either_claim(client, gateway, app):
    sc_text, st_text = "SC applicants qualify for this.", "ST applicants qualify for this."
    claims = [claim(sc_text, "income must be below"), claim(st_text, "at least 18 years old")]
    compiled = {
        sc_text: (cmp("social_category", "eq", "sc"), "category"),
        st_text: (cmp("social_category", "eq", "st"), "category"),
    }
    run_id = await start(client, gateway, "either", claims=claims, compiled=compiled)
    view = await wait_for_question(client, run_id)
    assert view["question"]["name"] == "social_category"
    assert len(await stored_rules(app, run_id)) == 2
    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {"social_category": "st"}})
    view = await wait_for_end(client, run_id)
    assert view["verdict"]["outcome"] == "MEETS_STATED_CRITERIA"
    assert len(view["verdict"]["met"]) == 2


async def test_rules_outage_is_partial_and_does_not_decide(client, gateway):
    gateway.replies["extract"] = [ExtractionResult(claims=[INCOME])]
    gateway.replies["rules"] = [ProviderUnavailable("status 503")]
    view = await wait_for_end(client, await upload(client, make_pdf(f"{DOCUMENT} outage")))
    assert view["status"] == "partial"
    assert view["verdict"]["outcome"] == "CANNOT_DETERMINE"
    assert len(view["claims"]) == 1


async def test_no_eligibility_claims_never_reads_as_passing(client, gateway):
    view = await wait_for_end(client, await upload(client, make_pdf(f"{DOCUMENT} none")))
    assert view["status"] == "completed"
    assert view["verdict"]["outcome"] == "CANNOT_DETERMINE"
    assert view["sentences"] == []
    assert "rules" not in gateway.prompts
    assert "script" not in gateway.prompts


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({}, 400, "INVALID_REQUEST"),
        ({"answers": {"age": 300}}, 400, "INVALID_ANSWER"),
        ({"answers": {"made_up": 1}}, 400, "INVALID_ANSWER"),
        ({"answers": {"is_bpl": True}}, 400, "INVALID_ANSWER"),
        ({"skip": ["is_bpl"]}, 400, "INVALID_ANSWER"),
    ],
)
async def test_bad_answers_leave_the_run_waiting(client, gateway, body, status, code):
    run_id = await start(client, gateway, f"invalid {body}", claims=[AGE], compiled={AGE_TEXT: AGE_RULE})
    await wait_for_question(client, run_id)
    response = await client.post(f"/v1/runs/{run_id}/answers", json=body)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "300" not in response.text
    view = (await client.get(f"/v1/runs/{run_id}")).json()
    assert view["status"] == "waiting_input"


async def test_answer_when_not_waiting_and_unknown_run(client, gateway):
    view_id = await upload(client, make_pdf(f"{DOCUMENT} finished"))
    await wait_for_end(client, view_id)
    response = await client.post(f"/v1/runs/{view_id}/answers", json={"skip": ["age"]})
    assert response.status_code == 400  # this finished run has no rule that asks for age
    missing = await client.post(f"/v1/runs/{uuid.uuid4()}/answers", json={"answers": {"age": 3}})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"


async def test_double_submit_resumes_only_once(client, gateway):
    run_id = await start(client, gateway, "double", claims=[AGE], compiled={AGE_TEXT: AGE_RULE})
    await wait_for_question(client, run_id)
    body = {"answers": {"age": 30}}
    first, second = await asyncio.gather(
        client.post(f"/v1/runs/{run_id}/answers", json=body),
        client.post(f"/v1/runs/{run_id}/answers", json=body),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 409]
    view = await wait_for_end(client, run_id)
    assert view["verdict"]["outcome"] == "MEETS_STATED_CRITERIA"
    assert len(events_of(view, "verdict")) == 1


async def test_no_profile_value_reaches_disk_or_the_view(client, gateway, app):
    run_id = await start(client, gateway, "private", claims=[INCOME], compiled={INCOME_TEXT: INCOME_RULE})
    await wait_for_question(client, run_id)
    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {"annual_income_inr": SECRET_INCOME}})
    view = await wait_for_end(client, run_id)
    assert view["verdict"]["outcome"] == "MEETS_STATED_CRITERIA"
    assert str(SECRET_INCOME) not in json.dumps(view)

    async with app.state.services.deps.sessions() as session:
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs", "run_events", "rules", "sentences"):
            found = await session.scalar(
                text(f"SELECT count(*) FROM {table} t WHERE encode(convert_to(t::text, 'UTF8'), 'escape') LIKE :s"),
                {"s": f"%{SECRET_INCOME}%"},
            )
            assert found == 0, table
        # bytea columns print as hex in t::text, and msgpack may store the number in binary.
        blobs = await session.execute(text("SELECT blob FROM checkpoint_writes WHERE blob IS NOT NULL"))
        packed = SECRET_INCOME.to_bytes(4, "big")
        for (blob,) in blobs:
            assert packed not in bytes(blob) and str(SECRET_INCOME).encode() not in bytes(blob)


async def test_restart_while_waiting_asks_again(client, gateway, app):
    deps = app.state.services.deps
    run_id = await start(client, gateway, "restart")
    view = await wait_for_question(client, run_id)
    first = view["question"]["name"]
    answers = {"age": 30, "annual_income_inr": 100000}
    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {first: answers[first]}})
    for _ in range(400):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] == "waiting_input" and view["question"]["name"] != first:
            break
        await asyncio.sleep(0.05)
    second = view["question"]["name"]
    assert second != first

    # What a restart does to the profile.
    deps.profiles._entries.clear()
    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {second: answers[second]}})
    for _ in range(400):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] == "waiting_input" and view["question"]["name"] == first:
            break
        await asyncio.sleep(0.05)
    assert view["question"]["name"] == first

    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {first: answers[first]}})
    view = await wait_for_end(client, run_id)
    assert view["verdict"]["outcome"] == "MEETS_STATED_CRITERIA"


def sentence(text, *indexes):
    return ScriptSentence(text=text, claim_indexes=list(indexes))


BENEFIT = claim("The scheme gives Rs. 2,50,000.", "income must be below Rs. 2,50,000", field="benefit")


async def test_script_cites_claims_and_starts_with_the_verdict(client, gateway, app):
    gateway.replies["script"] = [ScriptResult(sentences=[sentence("The scheme gives Rs. 2,50,000.", 0)])]
    run_id = await start(client, gateway, "script", claims=[BENEFIT], compiled={})
    view = await wait_for_end(client, run_id)
    assert events_of(view, "script_ready") == [{"sentences": 1}]
    assert [s["source_text"] for s in view["sentences"]] == ["The scheme gives Rs. 2,50,000."]
    assert view["sentences"][0]["claim_ids"] == [view["claims"][0]["id"]]
    assert view["sentences"][0]["guard_status"] == "passed"


async def test_verdict_sentence_is_fixed_text_citing_its_claim(client, gateway, app):
    gateway.replies["script"] = [ScriptResult(sentences=[sentence("Income is one criterion.", 0)])]
    run_id = await start(client, gateway, "fixed", claims=[AGE], compiled={AGE_TEXT: AGE_RULE})
    await wait_for_question(client, run_id)
    await client.post(f"/v1/runs/{run_id}/answers", json={"answers": {"age": 30}})
    view = await wait_for_end(client, run_id)
    first = view["sentences"][0]
    assert first["source_text"] == "You appear to meet the eligibility criteria this document states."
    assert first["claim_ids"] == view["verdict"]["met"]
    assert "MEETS" not in gateway.prompts["script"][0]
    assert "30" not in gateway.prompts["script"][0]


async def test_script_regenerates_once_and_drops_what_stays_invalid(client, gateway, app):
    invented = sentence("You get Rs. 9,99,999.", 0)
    ghost = sentence("This cites nothing real.", 42)
    fine = sentence("The scheme gives Rs. 2,50,000.", 0)
    gateway.replies["script"] = [
        ScriptResult(sentences=[invented, ghost]),
        ScriptResult(sentences=[invented, fine]),
    ]
    run_id = await start(client, gateway, "regen", claims=[BENEFIT], compiled={})
    view = await wait_for_end(client, run_id)
    assert [s["source_text"] for s in view["sentences"]] == ["The scheme gives Rs. 2,50,000."]
    assert events_of(view, "retry") == [{"reason": "SCRIPT_INVALID", "attempt": 1}]
    assert len(gateway.prompts["script"]) == 2
    assert "9,99,999" in gateway.prompts["script"][1]


async def test_script_outage_keeps_the_run_and_marks_it_partial(client, gateway):
    gateway.replies["script"] = [ProviderUnavailable("status 503")]
    run_id = await start(client, gateway, "script down", claims=[BENEFIT], compiled={})
    view = await wait_for_end(client, run_id)
    assert view["status"] == "partial"
    assert len(view["claims"]) == 1
    assert view["sentences"] == []
