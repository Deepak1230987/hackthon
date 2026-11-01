import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.claims.schemas import CandidateClaim, ExtractionResult
from app.db.models import Rule, Sentence
from app.graph.nodes.compile_rules import CompiledClaim, RulesResult
from app.graph.nodes.script import ScriptResult, ScriptSentence
from app.providers.gateway import ProviderUnavailable
from tests.conftest import make_pdf
from tests.integration.test_claims_flow import events_of, wait_for_end
from tests.integration.test_runs import upload

pytestmark = pytest.mark.integration

TEXT = "You get Rs. 6000 a year."
DOCUMENT = "You get Rs. 6000 a year from the scheme."
GOOD_HINDI = "आपको एक वर्ष में 6000 रुपये मिलते हैं।"
WRONG_HINDI = "आपको एक वर्ष में 8000 रुपये मिलते हैं।"


def prepare(gateway, sentences=(TEXT,)):
    gateway.replies["extract"] = [
        ExtractionResult(
            claims=[
                CandidateClaim(
                    field="benefit", text=TEXT, clause_ordinals=[1], quote="get Rs. 6000 a year"
                )
            ]
        )
    ]
    gateway.replies["script"] = [
        ScriptResult(sentences=[ScriptSentence(text=s, claim_indexes=[0]) for s in sentences])
    ]


async def run(client, gateway, tag, sentences=(TEXT,)):
    prepare(gateway, sentences)
    return await wait_for_end(client, await upload(client, make_pdf(f"{DOCUMENT} {tag}")))


async def stored(app, view):
    async with app.state.services.deps.sessions() as session:
        return (
            await session.scalars(
                select(Sentence).where(Sentence.run_id == uuid.UUID(view["id"])).order_by(Sentence.ordinal)
            )
        ).all()


async def test_sentence_is_translated_guarded_and_spoken(app, client, gateway, storage):
    gateway.sarvam.translations[TEXT] = GOOD_HINDI
    view = await run(client, gateway, "happy")
    assert view["status"] == "completed"
    sentence = (await stored(app, view))[0]
    assert sentence.translated_text == GOOD_HINDI
    assert sentence.translator == "sarvam"
    assert sentence.guard_status == "passed"
    assert sentence.audio_path.startswith("audio/")
    assert storage.objects[sentence.audio_path] == b"mp3:" + GOOD_HINDI.encode()
    assert len(events_of(view, "sentence_translated")) == 1
    assert events_of(view, "sentence_ready") == [{"sentence_id": str(sentence.id)}]

    name = sentence.audio_path.split("/")[1]
    served = await client.get(f"/v1/audio/{name}")
    assert served.content == b"mp3:" + GOOD_HINDI.encode()
    assert served.headers["content-type"] == "audio/mpeg"


async def test_changed_amount_is_caught_and_retried_with_the_llm(app, client, gateway):
    gateway.sarvam.translations[TEXT] = WRONG_HINDI
    gateway.llm_translation = GOOD_HINDI
    view = await run(client, gateway, "caught")
    failed = events_of(view, "guard_failed")
    assert failed[0]["reason"] == "NUMBER_CHANGED"
    assert failed[0]["attempt"] == 1
    sentence = (await stored(app, view))[0]
    assert sentence.translated_text == GOOD_HINDI
    assert sentence.translator == "llm"
    assert sentence.guard_status == "passed"
    assert gateway.sarvam.translate_calls == 1  # Sarvam would only repeat itself.


async def test_amount_that_stays_wrong_is_flagged_and_not_spoken(app, client, gateway):
    gateway.sarvam.translations[TEXT] = WRONG_HINDI
    gateway.llm_translation = WRONG_HINDI
    view = await run(client, gateway, "flagged")
    assert view["status"] == "completed"
    sentence = (await stored(app, view))[0]
    assert sentence.guard_status == "flagged"
    assert sentence.audio_path is None
    assert gateway.sarvam.tts_calls == 0
    assert [f["attempt"] for f in events_of(view, "guard_failed")] == [1, 2]


async def test_changed_meaning_is_caught(app, client, gateway):
    gateway.sarvam.translations[TEXT] = GOOD_HINDI
    gateway.meaning_label = "CHANGED"
    gateway.llm_translation = GOOD_HINDI
    view = await run(client, gateway, "meaning")
    assert events_of(view, "guard_failed")[0]["reason"] == "MEANING_CHANGED"
    assert (await stored(app, view))[0].guard_status == "flagged"


async def test_minor_difference_passes(app, client, gateway):
    gateway.sarvam.translations[TEXT] = GOOD_HINDI
    gateway.meaning_label = "MINOR_DIFF"
    view = await run(client, gateway, "minor")
    assert (await stored(app, view))[0].guard_status == "passed"


async def test_failed_number_check_spends_no_llm_call(client, gateway):
    gateway.sarvam.translations[TEXT] = WRONG_HINDI
    gateway.llm_translation = WRONG_HINDI
    await run(client, gateway, "free")
    assert "meaning" not in gateway.prompts


async def test_meaning_is_checked_in_batches(client, gateway):
    sentences = [TEXT] * 10
    gateway.sarvam.translations[TEXT] = GOOD_HINDI
    await run(client, gateway, "batch", sentences)
    assert len(gateway.prompts["meaning"]) == 2


async def test_without_sarvam_the_llm_translates_and_the_text_remains(app, client, gateway):
    gateway.sarvam.translate_fails = True
    gateway.sarvam.tts_fails = True
    # Text no earlier test has spoken, so there's no cached audio to find.
    gateway.llm_translation = "आपको हर वर्ष 6000 रुपये दिए जाते हैं।"
    view = await run(client, gateway, "nokey")
    assert view["status"] == "completed"
    sentence = (await stored(app, view))[0]
    assert sentence.translated_text == gateway.llm_translation
    assert sentence.translator == "llm"
    assert sentence.audio_path is None
    assert [f["to"] for f in events_of(view, "failover")] == ["the AI model", "text only"]


async def test_no_provider_at_all_shows_the_english_flagged(app, client, gateway):
    gateway.sarvam.translate_fails = True
    gateway.replies["translate"] = [ProviderUnavailable("down"), ProviderUnavailable("down")]
    view = await run(client, gateway, "down")
    assert view["status"] == "completed"
    sentence = (await stored(app, view))[0]
    assert sentence.guard_status == "flagged"
    assert sentence.translated_text is None
    assert sentence.source_text == TEXT


async def test_same_sentence_reuses_its_audio(client, gateway, storage):
    gateway.sarvam.translations[TEXT] = GOOD_HINDI
    await run(client, gateway, "cache one")
    calls = gateway.sarvam.tts_calls
    await run(client, gateway, "cache two")
    assert gateway.sarvam.tts_calls == calls


@pytest.mark.parametrize("name", ["../secret", "abc.mp3", "a" * 64 + ".wav"])
async def test_audio_route_rejects_other_names(client, name):
    assert (await client.get(f"/v1/audio/{name}")).status_code == 404


async def paused_run(app, client, gateway, tag):
    text = "Applicants must be students."
    gateway.replies["extract"] = [
        ExtractionResult(
            claims=[
                CandidateClaim(field="eligibility", text=text, clause_ordinals=[1], quote="must be students")
            ]
        )
    ]
    gateway.replies["rules"] = [
        RulesResult(
            rules=[
                CompiledClaim(
                    index=0,
                    expr='{"type": "cmp", "field": "is_student", "op": "eq", "value": true}',
                )
            ]
        )
    ]
    run_id = await upload(client, make_pdf(f"Applicants must be students. {tag}"))
    view = {}
    for _ in range(400):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] in ("waiting_input", "completed", "partial", "failed"):
            break
        await asyncio.sleep(0.05)
    assert view["status"] == "waiting_input", view
    async with app.state.services.deps.sessions() as session:
        assert (await session.scalars(select(Rule).where(Rule.run_id == uuid.UUID(run_id)))).first()
    return run_id


def recording(field="is_student", content=b"sound", content_type="audio/webm"):
    return {
        "files": {"audio": ("answer.webm", content, content_type)},
        "data": {"field": field},
    }


async def test_spoken_yes_is_read_without_an_llm_call(app, client, gateway):
    run_id = await paused_run(app, client, gateway, "stt plain")
    gateway.sarvam.stt_reply = ("जी हाँ", 0.9)
    response = await client.post(f"/v1/runs/{run_id}/stt", **recording())
    assert response.json() == {"transcript": "जी हाँ", "parsed": True, "confidence": 1.0}
    assert "answer" not in gateway.prompts
    # Reading it isn't answering it. The citizen has to confirm first.
    assert (await client.get(f"/v1/runs/{run_id}")).json()["status"] == "waiting_input"


async def test_unclear_answer_goes_to_the_llm(app, client, gateway):
    from app.voice.answers import ParsedAnswer

    run_id = await paused_run(app, client, gateway, "stt llm")
    gateway.sarvam.stt_reply = ("मैं कॉलेज में पढ़ता हूँ", 0.9)
    gateway.replies["answer"] = [ParsedAnswer(value="true", confidence=0.8)]
    response = await client.post(f"/v1/runs/{run_id}/stt", **recording())
    assert response.json()["parsed"] is True
    assert response.json()["confidence"] == 0.8


@pytest.mark.parametrize("reply", [("", 0.9), ("हाँ", 0.1)])
async def test_empty_or_unclear_speech_asks_again(app, client, gateway, reply):
    run_id = await paused_run(app, client, gateway, f"stt empty {reply[1]}{reply[0]}")
    gateway.sarvam.stt_reply = reply
    response = await client.post(f"/v1/runs/{run_id}/stt", **recording())
    assert response.json() == {"transcript": "", "parsed": None, "confidence": 0.0}


async def test_stt_is_limited_to_the_question_and_to_short_audio(app, client, gateway):
    run_id = await paused_run(app, client, gateway, "stt limits")
    assert (await client.post(f"/v1/runs/{run_id}/stt", **recording(field="age"))).status_code == 400
    big = recording(content=b"x" * (2 * 1024 * 1024 + 1))
    assert (await client.post(f"/v1/runs/{run_id}/stt", **big)).status_code == 413
    wrong = recording(content_type="application/pdf")
    assert (await client.post(f"/v1/runs/{run_id}/stt", **wrong)).json()["error"]["code"] == "INVALID_AUDIO"


async def test_speech_outage_tells_the_citizen_to_type(app, client, gateway):
    run_id = await paused_run(app, client, gateway, "stt down")
    gateway.sarvam.stt_fails = True
    response = await client.post(f"/v1/runs/{run_id}/stt", **recording())
    assert response.status_code == 503
    assert response.json()["error"]["action"] == "type"


async def test_transcript_is_never_stored(app, client, gateway):
    run_id = await paused_run(app, client, gateway, "stt private")
    gateway.sarvam.stt_reply = ("गुप्त उत्तर 987654", 0.9)
    await client.post(f"/v1/runs/{run_id}/stt", **recording())
    view = httpx.Response(200, content=(await client.get(f"/v1/runs/{run_id}")).content)
    assert "987654" not in view.text
