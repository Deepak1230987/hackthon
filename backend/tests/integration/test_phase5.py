import asyncio
import uuid

import pymupdf
import pytest
from sqlalchemy import select

from app.api.qa import ABSTENTION, ABSTENTIONS, GroundedAnswer
from app.claims.schemas import EntailmentResult, EntailmentVerdict, ExtractionResult
from app.db.models import Clause, Run
from app.providers.gateway import ProviderUnavailable
from tests.conftest import make_pdf
from tests.integration.test_claims_flow import wait_for_end
from tests.integration.test_runs import upload

pytestmark = pytest.mark.integration

DOCUMENT = "The scholarship pays Rs. 12,000 per year to each selected student."
ANSWER = "Each selected student gets Rs. 12,000 per year."
QUOTE = "pays Rs. 12,000 per year"
HINDI = "प्रत्येक चयनित छात्र को प्रति वर्ष 12,000 रुपये मिलते हैं।"


def grounded(answer=ANSWER, quote=QUOTE, ordinals=(1,)):
    return GroundedAnswer(answer=answer, clause_ordinals=list(ordinals), quote=quote)


async def finished_run(client, tag):
    view = await wait_for_end(client, await upload(client, make_pdf(f"{DOCUMENT} {tag}")))
    assert view["status"] == "completed"
    return view["id"]


async def ask(client, run_id, question="How much do I get?", **extra):
    return await client.post(f"/v1/runs/{run_id}/qa", json={"question": question, **extra})


async def test_a_supported_answer_is_translated_spoken_and_cited(client, gateway, storage):
    run_id = await finished_run(client, "supported")
    gateway.replies["qa"] = [grounded()]
    gateway.sarvam.translations[ANSWER] = HINDI
    response = await ask(client, run_id)
    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert body["answer"] == HINDI
    assert body["answer_en"] == ANSWER
    assert body["language"] == "hi"
    assert [c["page"] for c in body["citations"]] == [1]
    assert storage.objects[body["audio_path"]] == b"mp3:" + HINDI.encode()


async def test_question_the_document_does_not_answer_gets_abstention(client, gateway):
    run_id = await finished_run(client, "null answer")
    gateway.replies["qa"] = [GroundedAnswer(answer=None)]
    entail_before = len(gateway.prompts.get("entail", []))
    body = (await ask(client, run_id, "Who won the cricket match?")).json()
    assert body["abstained"] is True
    assert body["answer"] == ABSTENTIONS["hi"]
    assert body["answer_en"] == ABSTENTION
    assert body["citations"] == []
    assert len(gateway.prompts.get("entail", [])) == entail_before


@pytest.mark.parametrize(
    "reply",
    [
        grounded(quote="this sentence is not in the document at all"),
        grounded(answer="Each student gets Rs. 50,000 per year."),
        grounded(ordinals=(999,)),
        grounded(ordinals=()),
    ],
    ids=["made-up quote", "changed number", "unknown clause", "no clause"],
)
async def test_an_answer_failing_the_code_checks_is_never_shown(client, gateway, reply):
    run_id = await finished_run(client, f"code check {uuid.uuid4()}")
    gateway.replies["qa"] = [reply]
    entail_before = len(gateway.prompts.get("entail", []))
    body = (await ask(client, run_id)).json()
    assert body["abstained"] is True
    assert "50,000" not in body["answer"]
    assert len(gateway.prompts.get("entail", [])) == entail_before


async def test_an_answer_the_source_does_not_support_is_never_shown(client, gateway):
    run_id = await finished_run(client, "not entailed")
    gateway.replies["qa"] = [grounded()]
    gateway.replies["entail"] = [
        EntailmentResult(verdicts=[EntailmentVerdict(index=0, label="PARTIAL")])
    ]
    assert (await ask(client, run_id)).json()["abstained"] is True


async def test_a_translation_with_a_changed_number_falls_back_to_checked_english(client, gateway):
    run_id = await finished_run(client, "bad translation")
    gateway.replies["qa"] = [grounded()]
    gateway.sarvam.translations[ANSWER] = "प्रत्येक छात्र को 90,000 रुपये मिलते हैं।"
    gateway.llm_translation = "प्रत्येक छात्र को 80,000 रुपये मिलते हैं।"
    body = (await ask(client, run_id)).json()
    assert body["abstained"] is False
    assert body["answer"] == ANSWER
    assert body["language"] == "en"
    assert body["audio_path"] is None


async def test_provider_failure_is_an_error_and_not_a_false_abstention(client, gateway):
    run_id = await finished_run(client, "provider down")
    gateway.replies["qa"] = [ProviderUnavailable("status 503")]
    response = await ask(client, run_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QA_UNAVAILABLE"


async def test_failed_embedding_still_finds_the_clauses(client, gateway):
    run_id = await finished_run(client, "no embedding")
    gateway.embed_fails = True
    gateway.replies["qa"] = [grounded()]
    assert (await ask(client, run_id)).json()["abstained"] is False


async def test_repeated_abstention_audio_is_only_paid_for_once(client, gateway):
    run_id = await finished_run(client, "audio cache")
    gateway.replies["qa"] = [GroundedAnswer(answer=None), GroundedAnswer(answer=None)]
    before = gateway.sarvam.tts_calls
    first = (await ask(client, run_id)).json()
    second = (await ask(client, run_id)).json()
    assert first["audio_path"] == second["audio_path"]
    assert gateway.sarvam.tts_calls == before + 1


async def test_question_limits(client, gateway, settings):
    run_id = await finished_run(client, "limits")
    assert (await ask(client, run_id, "   ")).json()["error"]["code"] == "INVALID_QUESTION"
    assert (await ask(client, run_id, "x" * 501)).json()["error"]["code"] == "INVALID_QUESTION"
    settings.max_questions_per_run = 1
    assert (await ask(client, run_id)).status_code == 200
    response = await ask(client, run_id)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "QUESTION_LIMIT"


async def test_question_is_refused_until_the_run_has_finished(client, app):
    run_id = await finished_run(client, "unfinished")
    async with app.state.services.deps.sessions() as session:
        (await session.get(Run, uuid.UUID(run_id))).status = "running"
        await session.commit()
    assert (await ask(client, run_id)).status_code == 409
    assert (await ask(client, uuid.uuid4())).status_code == 404


async def test_the_question_is_not_stored(client, gateway, app):
    run_id = await finished_run(client, "privacy")
    secret = "my aadhaar is 999988887777"
    gateway.replies["qa"] = [GroundedAnswer(answer=None)]
    await ask(client, run_id, secret)
    view = (await client.get(f"/v1/runs/{run_id}")).text
    assert secret not in view
    assert "999988887777" not in view


async def test_spoken_question_returns_what_was_heard(client, gateway, settings):
    run_id = await finished_run(client, "spoken")
    gateway.sarvam.stt_reply = ("मुझे कितने पैसे मिलेंगे", 0.9)
    files = {"audio": ("q", b"sound", "audio/webm")}
    response = await client.post(f"/v1/runs/{run_id}/qa/stt", files=files)
    assert response.json() == {"transcript": "मुझे कितने पैसे मिलेंगे"}

    settings.max_stt_per_run = 1
    response = await client.post(f"/v1/runs/{run_id}/qa/stt", files=files)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "SPEECH_LIMIT"


def long_pdf(pages: int, tag: str) -> bytes:
    document = pymupdf.open()
    for number in range(1, pages + 1):
        # Letters too, or lines differing only by a number would be taken for a page header.
        word = "".join(chr(97 + int(digit)) for digit in str(number))
        document.new_page().insert_text((72, 72), f"Rule {number} {word} of the {tag} scheme applies.")
    return document.tobytes()


async def test_a_300_page_document_asks_for_a_range_then_reads_only_those_pages(
    client, app, gateway, settings
):
    settings.max_pdf_mb = 10
    stopped = await wait_for_end(client, await upload(client, long_pdf(300, "long")))
    assert stopped["status"] == "failed"
    assert stopped["error"]["code"] == "DOC_TOO_LONG"
    assert stopped["error"]["details"] == {"page_count": 300, "max_pages": 200}

    gateway.replies["extract"] = [ExtractionResult(claims=[])]
    extract_before = len(gateway.prompts.get("extract", []))
    response = await client.post(
        f"/v1/runs/{stopped['id']}/page-range", json={"from": 11, "to": 13}
    )
    assert response.status_code == 202
    view = await wait_for_end(client, response.json()["run_id"])
    assert view["status"] == "completed", view["error"]
    assert view["page_range"] == {"from": 11, "to": 13}

    async with app.state.services.deps.sessions() as session:
        pages = set(
            await session.scalars(
                select(Clause.page).where(Clause.document_id == uuid.UUID(view["document"]["id"]))
            )
        )
    assert pages == {11, 12, 13}
    prompt = gateway.prompts["extract"][extract_before]
    assert "Rule 11 " in prompt and "Rule 13 " in prompt and "Rule 14 " not in prompt


async def test_a_second_range_uses_only_its_own_pages(client, gateway, settings):
    settings.max_pdf_mb = 10
    settings.max_pages = 5
    stopped = await wait_for_end(client, await upload(client, long_pdf(9, "two ranges")))
    for first, last in ((1, 2), (7, 8)):
        before = len(gateway.prompts.get("extract", []))
        response = await client.post(
            f"/v1/runs/{stopped['id']}/page-range", json={"from": first, "to": last}
        )
        await wait_for_end(client, response.json()["run_id"])
    prompt = gateway.prompts["extract"][before]
    assert "Rule 7 " in prompt and "Rule 1 " not in prompt


@pytest.mark.parametrize(
    ("first", "last", "code"),
    [(0, 5, 400), (5, 4, 400), (299, 301, 400), (1, 201, 400)],
)
async def test_an_invalid_range_is_refused(client, settings, first, last, code):
    settings.max_pdf_mb = 10
    stopped = await wait_for_end(client, await upload(client, long_pdf(300, f"bad {first} {last}")))
    response = await client.post(
        f"/v1/runs/{stopped['id']}/page-range", json={"from": first, "to": last}
    )
    assert response.status_code == code
    assert response.json()["error"]["code"] == "INVALID_PAGE_RANGE"


async def test_a_range_is_refused_when_the_run_did_not_ask_for_one(client):
    run_id = await finished_run(client, "no range needed")
    response = await client.post(f"/v1/runs/{run_id}/page-range", json={"from": 1, "to": 1})
    assert response.status_code == 409


async def test_sixth_rapid_run_is_limited(client, settings, app):
    settings.max_runs_per_ip = 5
    # Earlier tests share this client address.
    async with app.state.services.deps.sessions() as session:
        await session.execute(Run.__table__.update().values(client_hash=None))
        await session.commit()
    results = await asyncio.gather(
        *(
            client.post(
                "/v1/documents",
                files={"file": ("a.pdf", make_pdf(f"{DOCUMENT} rapid {n}"), "application/pdf")},
                data={"language": "hi"},
            )
            for n in range(7)
        )
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [202] * 5 + [429] * 2
    refused = next(r for r in results if r.status_code == 429).json()["error"]
    assert refused["code"] == "RATE_LIMITED"
    assert 0 < refused["details"]["retry_after_s"] <= 600

    accepted = [r.json()["run_id"] for r in results if r.status_code == 202]
    async with app.state.services.deps.sessions() as session:
        stored = await session.scalar(select(Run.client_hash).where(Run.id == uuid.UUID(accepted[0])))
    assert len(stored) == 64
    assert "127.0.0.1" not in stored
    for run_id in accepted:
        await wait_for_end(client, run_id)


async def test_limit_covers_url_runs_and_old_runs_stop_counting(client, settings, app):
    settings.max_runs_per_ip = 1
    async with app.state.services.deps.sessions() as session:
        await session.execute(Run.__table__.update().values(client_hash=None))
        await session.commit()
    first = await upload(client, make_pdf(f"{DOCUMENT} window"))
    await wait_for_end(client, first)
    response = await client.post(
        "/v1/documents", json={"url": "https://8.8.8.8/a.pdf", "language": "hi"}
    )
    assert response.status_code == 429

    settings.run_limit_window_s = 0
    response = await client.post(
        "/v1/documents",
        files={"file": ("a.pdf", make_pdf(f"{DOCUMENT} later"), "application/pdf")},
        data={"language": "hi"},
    )
    assert response.status_code == 202
    await wait_for_end(client, response.json()["run_id"])


async def test_queue_position_counts_the_runs_ahead(client, app, gateway):
    async with app.state.services.deps.sessions() as session:
        earlier = Run(language="hi", status="queued", source={})
        session.add(earlier)
        await session.commit()
        later = Run(language="hi", status="queued", source={})
        session.add(later)
        await session.commit()
        earlier_id, later_id = earlier.id, later.id
    earlier_view = (await client.get(f"/v1/runs/{earlier_id}")).json()
    later_view = (await client.get(f"/v1/runs/{later_id}")).json()
    assert later_view["queue_position"] == earlier_view["queue_position"] + 1
    async with app.state.services.deps.sessions() as session:
        await session.execute(
            Run.__table__.update()
            .where(Run.id.in_([earlier_id, later_id]))
            .values(status="failed")
        )
        await session.commit()
    assert (await client.get(f"/v1/runs/{later_id}")).json()["queue_position"] is None


async def test_a_correct_answer_with_a_bad_quote_gets_a_second_try(client, gateway):
    run_id = await finished_run(client, "second try")
    gateway.replies["qa"] = [grounded(quote="words that are not in the clause"), grounded()]
    gateway.sarvam.translations[ANSWER] = HINDI
    before = len(gateway.prompts.get("qa", []))
    body = (await ask(client, run_id)).json()
    assert body["abstained"] is False
    assert body["answer"] == HINDI
    prompts = gateway.prompts["qa"][before:]
    assert len(prompts) == 2
    assert "failed an automatic check" not in prompts[0]
    assert "failed an automatic check" in prompts[1]


async def test_an_answer_that_fails_twice_is_still_never_shown(client, gateway):
    run_id = await finished_run(client, "fails twice")
    bad = grounded(quote="words that are not in the clause")
    gateway.replies["qa"] = [bad, bad]
    body = (await ask(client, run_id)).json()
    assert body["abstained"] is True
    assert body["citations"] == []


async def test_abstention_costs_no_second_try(client, gateway):
    run_id = await finished_run(client, "no second try")
    gateway.replies["qa"] = [GroundedAnswer(answer=None)]
    before = len(gateway.prompts.get("qa", []))
    await ask(client, run_id, "Who won the cricket match?")
    assert len(gateway.prompts["qa"]) == before + 1


async def test_clauses_beside_a_match_reach_the_model(client, gateway):
    document = pymupdf.open()
    page = document.new_page()
    for line in range(30):
        page.insert_text((72, 40 + line * 24), f"{line + 1}. Rule number {line + 1} of the scheme.")
    run_id = (await wait_for_end(client, await upload(client, document.tobytes())))["id"]
    gateway.replies["qa"] = [GroundedAnswer(answer=None)]
    await ask(client, run_id)
    sent = gateway.prompts["qa"][-1].count("Rule number")
    assert sent > 12
