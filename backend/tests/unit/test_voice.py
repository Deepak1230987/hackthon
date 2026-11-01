import base64
import json
import time

import httpx
import pytest

from app.config import Settings
from app.eligibility.fields import FIELDS
from app.graph.nodes.tts import audio_path
from app.providers.errors import ProviderUnavailable
from app.providers.ratelimit import TokenBucket
from app.providers.sarvam import Sarvam
from app.voice.answers import checked_value, quick_parse
from app.voice.guard import numbers_match


@pytest.mark.parametrize(
    ("source", "translated"),
    [
        ("You get Rs. 6000 a year.", "आपको एक वर्ष में 6000 रुपये मिलते हैं।"),
        ("Income must be below Rs. 2.5 lakh.", "आय 2.5 लाख रुपये से कम होनी चाहिए।"),
        ("Income must be below 2,50,000 rupees.", "आय ₹2,50,000 से कम होनी चाहिए।"),
        ("The cut-off date is 01.02.2019.", "अंतिम तिथि 1 फरवरी 2019 है।"),
        ("Apply within 30 days.", "30 दिनों के भीतर आवेदन करें।"),
        ("Reservation is 50 percent.", "आरक्षण 50 प्रतिशत है।"),
        ("Apply at the office.", "कार्यालय में आवेदन करें।"),
        # Both wrongly flagged on a real scholarship document.
        ("Disbursement is 31st October.", "भुगतान 31 अक्टूबर को होता है।"),
        ("It is available for only one year.", "यह सिर्फ 1 साल के लिए मिलती है।"),
        ("It is available for 1 year.", "यह एक साल के लिए मिलती है।"),
        ("Verification is due by 31stAugust.", "सत्यापन 31 अगस्त तक होना चाहिए।"),
    ],
)
def test_same_numbers_pass(source, translated):
    assert numbers_match(source, translated)


@pytest.mark.parametrize(
    ("source", "translated"),
    [
        ("You get Rs. 6000 a year.", "आपको एक वर्ष में 8000 रुपये मिलते हैं।"),
        ("Income must be below Rs. 2.5 lakh.", "आय 3.5 लाख रुपये से कम होनी चाहिए।"),
        ("Income must be below Rs. 2.5 lakh.", "आय 2.5 करोड़ रुपये से कम होनी चाहिए।"),
        ("The cut-off date is 01.02.2019.", "अंतिम तिथि 2 जनवरी 2019 है।"),
        ("Apply within 30 days.", "दिनों के भीतर आवेदन करें।"),
        ("Apply at the office.", "10 दिनों में कार्यालय में आवेदन करें।"),
        ("Disbursement is 31st October.", "भुगतान 30 अक्टूबर को होता है।"),
        ("It is available for only one year.", "यह सिर्फ 2 साल के लिए मिलती है।"),
        ("You get 2 installments.", "आपको 3 किस्तें मिलती हैं।"),
    ],
)
def test_changed_missing_or_added_numbers_fail(source, translated):
    assert not numbers_match(source, translated)


@pytest.mark.parametrize(
    ("field", "transcript", "expected"),
    [
        ("is_student", "हाँ", True),
        ("is_student", "जी हां।", True),
        ("is_student", "नहीं", False),
        ("is_student", "Yes.", True),
        ("age", "मेरी उम्र 25 साल है", 25),
        ("age", "२५", 25),
        ("annual_income_inr", "2.5 लाख रुपये", 250000),
        ("annual_income_inr", "₹1,20,000", 120000),
        ("gender", "female", "female"),
    ],
)
def test_clear_answers_need_no_llm(field, transcript, expected):
    definition = FIELDS[field]
    assert checked_value(definition, quick_parse(definition, transcript)) == expected


@pytest.mark.parametrize(
    ("field", "transcript"),
    [
        ("is_student", "मैं पिछले साल तक पढ़ता था"),
        ("age", "पच्चीस साल"),
        ("age", "20 या 25 साल"),
        ("gender", "मैं एक महिला हूँ"),
    ],
)
def test_unclear_answers_go_to_the_llm(field, transcript):
    assert quick_parse(FIELDS[field], transcript) is None


def test_answer_out_of_range_is_asked_again():
    assert checked_value(FIELDS["age"], "300") is None


def test_llm_booleans_become_booleans():
    assert checked_value(FIELDS["is_student"], "true") is True
    assert checked_value(FIELDS["is_student"], "maybe") is None


def test_audio_cache_key_covers_everything_that_changes_the_sound():
    base = audio_path("m", "v", "hi", "text")
    assert base.startswith("audio/") and base.endswith(".mp3")
    assert base == audio_path("m", "v", "hi", "text")
    for other in (
        audio_path("x", "v", "hi", "text"),
        audio_path("m", "x", "hi", "text"),
        audio_path("m", "v", "bn", "text"),
        audio_path("m", "v", "hi", "other"),
    ):
        assert other != base


async def test_token_bucket_spaces_calls_out():
    bucket = TokenBucket(per_second=20)
    started = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    assert time.monotonic() - started >= 0.09


def sarvam(handler, **config):
    settings = Settings(
        _env_file=None, database_url="postgresql://x", sarvam_api_key="k", **config
    )
    client = Sarvam(settings)
    client._client = httpx.AsyncClient(
        base_url="https://api.sarvam.ai",
        headers={"api-subscription-key": "k"},
        transport=httpx.MockTransport(handler),
    )
    client._buckets = {name: TokenBucket(10_000) for name in client._buckets}
    return client


@pytest.fixture
def no_waiting(monkeypatch):
    async def instantly(_):
        return None

    monkeypatch.setattr("app.providers.sarvam.asyncio.sleep", instantly)


async def test_translate_sends_what_sarvam_documents():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content), path=request.url.path, key=request.headers["api-subscription-key"])
        return httpx.Response(200, json={"translated_text": " नमस्ते "})

    assert await sarvam(handler, translate_model="sarvam-translate:v1").translate("Hello", "hi") == "नमस्ते"
    assert sent["path"] == "/translate"
    assert sent["key"] == "k"
    assert sent["target_language_code"] == "hi-IN"
    assert sent["numerals_format"] == "international"


async def test_tts_returns_decoded_mp3():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content), path=request.url.path)
        return httpx.Response(200, json={"audios": [base64.b64encode(b"sound").decode()]})

    assert await sarvam(handler).tts("नमस्ते", "hi") == b"sound"
    assert sent["path"] == "/text-to-speech"
    assert sent["language_code"] == "hi-IN"
    assert sent["output_audio_codec"] == "mp3"
    assert sent["speaker"] == "ritu_hi_customer"


async def test_stt_asks_sarvam_to_detect_the_language():
    def handler(request):
        assert b'name="language_code"' in request.content and b"unknown" in request.content
        return httpx.Response(200, json={"transcript": " हाँ ", "language_probability": 0.9})

    assert await sarvam(handler).stt(b"audio", "audio/webm") == ("हाँ", 0.9)


async def test_out_of_credit_stops_all_further_calls(no_waiting):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(402, json={})

    client = sarvam(handler)
    with pytest.raises(ProviderUnavailable, match="402"):
        await client.translate("a", "hi")
    assert client.out_of_credit
    with pytest.raises(ProviderUnavailable, match="out of credit"):
        await client.tts("a", "hi")
    assert len(calls) == 1


async def test_rate_limit_is_retried(no_waiting):
    replies = [httpx.Response(429, json={}), httpx.Response(200, json={"translated_text": "ठीक"})]
    assert await sarvam(lambda r: replies.pop(0)).translate("a", "hi") == "ठीक"


async def test_no_key_never_calls_sarvam():
    client = Sarvam(Settings(_env_file=None, database_url="postgresql://x"))
    with pytest.raises(ProviderUnavailable, match="no Sarvam key"):
        await client.translate("a", "hi")
