import json

import httpx
import pytest

from app.config import Settings
from app.providers.gateway import Gateway, ProviderUnavailable

ITEMS = [{"kind": "para", "text": "नियम 1"}, {"kind": "junk", "text": "x"}, {"kind": "para", "text": " "}]
USABLE = [{"kind": "para", "text": "नियम 1"}]
RECITATION = {"candidates": [{"finishReason": "RECITATION"}]}


def _gateway(gemini, openai=None, **config):
    settings = Settings(
        _env_file=None,
        database_url="postgresql://x",
        gemini_api_key="g",
        ocr_model="primary",
        ocr_fallback_model="secondary",
        **config,
    )
    gateway = Gateway(settings)
    gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(gemini))
    if openai:
        gateway._openai = httpx.AsyncClient(transport=httpx.MockTransport(openai))
    return gateway


async def test_ocr_keeps_only_usable_items():
    reply = {"candidates": [{"content": {"parts": [{"text": json.dumps(ITEMS)}]}}]}
    gateway = _gateway(lambda r: httpx.Response(200, json=reply))
    assert await gateway.vision_ocr(b"png") == USABLE


async def test_recitation_is_reported_and_skips_the_other_gemini_model():
    calls = []

    def gemini(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=RECITATION)

    with pytest.raises(ProviderUnavailable, match="^recitation$"):
        await _gateway(gemini).vision_ocr(b"png")
    assert len(calls) == 1


async def test_recitation_falls_back_to_openai_when_configured():
    sent = {}

    def openai(request):
        sent.update(json.loads(request.content))
        content = json.dumps({"items": ITEMS})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    gateway = _gateway(
        lambda r: httpx.Response(200, json=RECITATION),
        openai,
        openai_api_key="o",
        llm_fallback_model="vision",
    )
    assert await gateway.vision_ocr(b"png") == USABLE
    assert sent["model"] == "vision"
    assert sent["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_openai_failure_keeps_both_reasons():
    gateway = _gateway(
        lambda r: httpx.Response(200, json=RECITATION),
        lambda r: httpx.Response(401),
        openai_api_key="o",
        llm_fallback_model="vision",
    )
    with pytest.raises(ProviderUnavailable, match="recitation, then OpenAI: status 401"):
        await gateway.vision_ocr(b"png")


async def test_openai_is_not_called_without_a_key():
    def openai(request):
        raise AssertionError("must not be called")

    gateway = _gateway(lambda r: httpx.Response(200, json=RECITATION), openai)
    with pytest.raises(ProviderUnavailable, match="^recitation$"):
        await gateway.vision_ocr(b"png")
