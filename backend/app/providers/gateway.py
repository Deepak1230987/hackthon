import asyncio
import base64
import json
import logging
import random
from typing import Any

import httpx

from app.config import Settings
from app.documents.ocr import OCR_KINDS, OCR_PROMPT, OCR_SCHEMA, OPENAI_OCR_SCHEMA

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_S = 45
BACKOFF_S = (1, 2, 4)
EMBED_BATCH = 64
RETRYABLE = {429, 500, 502, 503, 504}
# A per-minute limit clears within this. Daily quotas ask for hours.
MAX_REQUESTED_DELAY_S = 65


class ProviderUnavailable(Exception):
    pass


def _requested_delay(response: httpx.Response) -> float | None:
    """The wait Gemini asks for in a RetryInfo detail, such as "34s"."""
    try:
        details = response.json()["error"]["details"]
        delay = next(d["retryDelay"] for d in details if d["@type"].endswith("RetryInfo"))
        return float(delay.rstrip("s"))
    except (KeyError, IndexError, TypeError, ValueError, StopIteration):
        return None


def _ocr_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"kind": item["kind"], "text": item["text"]}
        for item in items
        if item["kind"] in OCR_KINDS and item["text"].strip()
    ]


class Gateway:
    """Calls to AI providers. Failover to OpenAI, circuit breaking and budgets join in phase 3."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            headers={"x-goog-api-key": settings.gemini_api_key}, timeout=TIMEOUT_S
        )
        self._openai = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.openai_api_key}"}, timeout=TIMEOUT_S
        )

    async def _post(self, model: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
        failure = "no attempt made"
        for delay in (*BACKOFF_S, None):
            wait = delay
            try:
                response = await self._client.post(f"{GEMINI_URL}/{model}:{method}", json=body)
                if response.status_code == 200:
                    return response.json()
                failure = f"status {response.status_code}"
                if response.status_code not in RETRYABLE:
                    break
                requested = _requested_delay(response)
                if requested is not None:
                    # A long wait means a daily quota has run out, so don't sit waiting for it.
                    if requested > MAX_REQUESTED_DELAY_S:
                        break
                    wait = max(delay or 0, requested) if delay is not None else None
            except httpx.HTTPError as exc:
                failure = type(exc).__name__
            if wait is not None:
                await asyncio.sleep(wait + random.random())
        log.warning("Gemini %s on %s failed: %s", method, model, failure)
        raise ProviderUnavailable(failure)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._settings.embedding_model
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            body = {
                "requests": [
                    {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}
                    for text in batch
                ]
            }
            result = await self._post(model, "batchEmbedContents", body)
            try:
                found = [item["values"] for item in result["embeddings"]]
            except (KeyError, TypeError) as exc:
                raise ProviderUnavailable(f"unusable reply: {type(exc).__name__}") from exc
            if len(found) != len(batch):
                raise ProviderUnavailable("unusable reply: wrong number of embeddings")
            vectors += found
        return vectors

    async def vision_ocr(self, image: bytes) -> list[dict[str, str]]:
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": OCR_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image).decode(),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": OCR_SCHEMA,
            },
        }
        settings = self._settings
        models = [model for model in (settings.ocr_model, settings.ocr_fallback_model) if model]
        failure = "no OCR model configured"
        for model in models:
            try:
                result = await self._post(model, "generateContent", body)
                candidate = result["candidates"][0]
                if candidate.get("finishReason") == "RECITATION":
                    # Gemini won't copy text it recognises, such as a quoted statute. Every
                    # Gemini model refuses alike, so only another provider can read this page.
                    failure = "recitation"
                    break
                parts = candidate["content"]["parts"]
                return _ocr_items(json.loads("".join(part.get("text", "") for part in parts)))
            except ProviderUnavailable as exc:
                failure = str(exc)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                failure = f"unusable reply: {type(exc).__name__}"
        if settings.openai_api_key and settings.llm_fallback_model:
            try:
                return await self._openai_ocr(image)
            except ProviderUnavailable as exc:
                failure = f"{failure}, then OpenAI: {exc}"
        raise ProviderUnavailable(failure)

    async def _openai_ocr(self, image: bytes) -> list[dict[str, str]]:
        url = f"data:image/png;base64,{base64.b64encode(image).decode()}"
        body = {
            "model": self._settings.llm_fallback_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            "response_format": {"type": "json_schema", "json_schema": OPENAI_OCR_SCHEMA},
        }
        try:
            response = await self._openai.post(OPENAI_URL, json=body)
            if response.status_code != 200:
                raise ProviderUnavailable(f"status {response.status_code}")
            content = response.json()["choices"][0]["message"]["content"]
            return _ocr_items(json.loads(content)["items"])
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(type(exc).__name__) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"unusable reply: {type(exc).__name__}") from exc

    async def close(self) -> None:
        await self._client.aclose()
        await self._openai.aclose()
