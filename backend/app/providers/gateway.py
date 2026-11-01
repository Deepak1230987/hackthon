import asyncio
import base64
import json
import logging
import random
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.documents.ocr import OCR_KINDS, OCR_PROMPT, OCR_SCHEMA, OPENAI_OCR_SCHEMA
from app.providers.budget import Budget
from app.providers.circuit import Circuit
from app.providers.errors import ProviderUnavailable
from app.providers.sarvam import Sarvam

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_S = 45
# Extracting from a long document takes far longer than one page of OCR.
LLM_TIMEOUT_S = 120
FAST_TASKS = {"triage", "meaning", "answer"}
CROSS_CHECKED_TASKS = {"entail"}
BACKOFF_S = (1, 2, 4)
EMBED_BATCH = 64
RETRYABLE = {429, 500, 502, 503, 504}
# A per-minute limit clears within this. Daily quotas ask for hours.
MAX_REQUESTED_DELAY_S = 65
OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")


Model = TypeVar("Model", bound=BaseModel)


def _is_openai(model: str) -> bool:
    return model.startswith(OPENAI_MODEL_PREFIXES)


def gemini_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gemini's response schema is a subset of JSON Schema, without references or unions."""
    defs = schema.get("$defs", {}) if defs is None else defs
    if "$ref" in schema:
        return gemini_schema(defs[schema["$ref"].rsplit("/", 1)[1]], defs)
    if "anyOf" in schema:
        real = [option for option in schema["anyOf"] if option.get("type") != "null"]
        return {**gemini_schema(real[0], defs), "nullable": True}
    result: dict[str, Any] = {"type": schema.get("type", "string").upper()}
    if "enum" in schema:
        result["enum"] = schema["enum"]
    if "const" in schema:
        result["enum"] = [schema["const"]]
    if "items" in schema:
        result["items"] = gemini_schema(schema["items"], defs)
    if "properties" in schema:
        result["properties"] = {
            name: gemini_schema(value, defs) for name, value in schema["properties"].items()
        }
        result["required"] = schema.get("required", [])
    return result


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
    """Calls to AI providers, with retries, failover to OpenAI, circuit breaking and budgets."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            headers={"x-goog-api-key": settings.gemini_api_key}, timeout=TIMEOUT_S
        )
        self._openai = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.openai_api_key}"}, timeout=TIMEOUT_S
        )
        self._circuits: dict[str, Circuit] = {}
        self.sarvam = Sarvam(settings)

    def _circuit(self, provider: str) -> Circuit:
        return self._circuits.setdefault(provider, Circuit())

    async def _post(
        self, model: str, method: str, body: dict[str, Any], timeout: float = TIMEOUT_S
    ) -> dict[str, Any]:
        failure = "no attempt made"
        for delay in (*BACKOFF_S, None):
            wait = delay
            try:
                response = await self._client.post(
                    f"{GEMINI_URL}/{model}:{method}", json=body, timeout=timeout
                )
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

    async def structured(
        self, task: str, prompt: str, schema: type[Model], budget: Budget
    ) -> Model:
        """A reply matching the schema, from the first provider able to give one."""
        settings = self._settings
        # Triage only decides whether to carry on, so it needn't use the slower model.
        primary = settings.llm_fast_model if task in FAST_TASKS else ""
        models = [primary or settings.llm_primary_model, settings.llm_fallback_model]
        if settings.cross_provider_verify and task in CROSS_CHECKED_TASKS:
            # A second provider is less likely to share the first one's mistake.
            models.reverse()
        failure = "no LLM model configured"
        previous = None
        for model in models:
            if not model or (_is_openai(model) and not settings.openai_api_key):
                continue
            provider, call = (
                ("openai", self._openai_text) if _is_openai(model) else ("gemini", self._gemini_text)
            )
            if previous:
                await budget.failover(previous, provider, failure)
            previous = provider
            circuit = self._circuit(provider)
            if circuit.is_open():
                failure = "circuit open"
                continue
            try:
                result = await self._validated(call, model, prompt, schema, budget)
            except ProviderUnavailable as exc:
                circuit.record_failure()
                failure = str(exc)
                log.warning("%s failed on %s: %s", task, provider, failure)
                continue
            circuit.record_success()
            return result
        raise ProviderUnavailable(failure)

    async def _validated(self, call, model: str, prompt: str, schema: type[Model], budget: Budget) -> Model:
        await budget.charge()
        reply = await call(model, prompt, schema)
        try:
            return schema.model_validate_json(reply)
        except ValidationError as exc:
            problem = str(exc)[:800]
        # One chance to fix it, by showing the model exactly what was wrong.
        await budget.charge()
        repair = (
            f"{prompt}\n\nYour previous reply was:\n{reply[:4000]}\n\n"
            f"It failed validation with:\n{problem}\n\nReply again with valid JSON."
        )
        reply = await call(model, repair, schema)
        try:
            return schema.model_validate_json(reply)
        except ValidationError as exc:
            raise ProviderUnavailable("reply did not match the schema") from exc

    async def _gemini_text(self, model: str, prompt: str, schema: type[BaseModel]) -> str:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": gemini_schema(schema.model_json_schema()),
            },
        }
        result = await self._post(model, "generateContent", body, timeout=LLM_TIMEOUT_S)
        try:
            candidate = result["candidates"][0]
            if "content" not in candidate or "parts" not in candidate["content"]:
                raise ProviderUnavailable(f"blocked: {candidate.get('finishReason', 'unknown')}")
            return "".join(part.get("text", "") for part in candidate["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            reason = (result.get("promptFeedback") or {}).get("blockReason", type(exc).__name__)
            raise ProviderUnavailable(f"blocked: {reason}") from exc

    async def _openai_text(self, model: str, prompt: str, schema: type[BaseModel]) -> str:
        shape = json.dumps(schema.model_json_schema())
        body = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "user", "content": f"{prompt}\n\nReply with JSON matching this schema:\n{shape}"}
            ],
            "response_format": {"type": "json_object"},
        }
        result = await self._openai_post(body)
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"unusable reply: {type(exc).__name__}") from exc

    async def _openai_post(self, body: dict[str, Any]) -> dict[str, Any]:
        failure = "no attempt made"
        for delay in (*BACKOFF_S, None):
            try:
                response = await self._openai.post(OPENAI_URL, json=body, timeout=LLM_TIMEOUT_S)
                if response.status_code == 200:
                    return response.json()
                failure = f"status {response.status_code}"
                if (
                    response.status_code == 400
                    and "temperature" in response.text
                    and "temperature" in body
                ):
                    # Some models accept only their default, so ask again without it.
                    body = {key: value for key, value in body.items() if key != "temperature"}
                    continue
                # Retrying can't help when the account has run out of credit.
                if response.status_code not in RETRYABLE or "insufficient_quota" in response.text:
                    break
            except httpx.HTTPError as exc:
                failure = type(exc).__name__
            if delay is not None:
                await asyncio.sleep(delay + random.random())
        log.warning("OpenAI on %s failed: %s", body.get("model"), failure)
        raise ProviderUnavailable(failure)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Gemini only: vectors from another model can't be compared with the stored ones.
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

    def _ocr_models(self) -> list[str]:
        settings = self._settings
        models = [model for model in (settings.ocr_model, settings.ocr_fallback_model) if model]
        if not any(_is_openai(model) for model in models):
            # Gemini refuses pages that quote known text, so keep a way to read them.
            llm_models = (settings.llm_fallback_model, settings.llm_primary_model)
            models += [model for model in llm_models if _is_openai(model)][:1]
        return models

    async def vision_ocr(self, image: bytes) -> list[dict[str, str]]:
        failure = "no OCR model configured"
        last_provider = None
        recited = False
        for model in self._ocr_models():
            is_openai = _is_openai(model)
            if (is_openai and not self._settings.openai_api_key) or (recited and not is_openai):
                continue
            provider, read = ("OpenAI", self._openai_ocr) if is_openai else ("Gemini", self._gemini_ocr)
            try:
                return await read(image, model)
            except ProviderUnavailable as exc:
                moved_on = last_provider not in (None, provider)
                failure = f"{failure}, then {provider}: {exc}" if moved_on else str(exc)
                recited = recited or str(exc) == "recitation"
                last_provider = provider
        raise ProviderUnavailable(failure)

    async def _gemini_ocr(self, image: bytes, model: str) -> list[dict[str, str]]:
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
        result = await self._post(model, "generateContent", body)
        try:
            candidate = result["candidates"][0]
            if candidate.get("finishReason") == "RECITATION":
                # Gemini won't copy text it recognises, such as a quoted statute. Every
                # Gemini model refuses alike, so only another provider can read this page.
                raise ProviderUnavailable("recitation")
            parts = candidate["content"]["parts"]
            return _ocr_items(json.loads("".join(part.get("text", "") for part in parts)))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"unusable reply: {type(exc).__name__}") from exc

    async def _openai_ocr(self, image: bytes, model: str) -> list[dict[str, str]]:
        url = f"data:image/png;base64,{base64.b64encode(image).decode()}"
        body = {
            "model": model,
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
        result = await self._openai_post(body)
        try:
            content = result["choices"][0]["message"]["content"]
            return _ocr_items(json.loads(content)["items"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"unusable reply: {type(exc).__name__}") from exc

    async def close(self) -> None:
        await self._client.aclose()
        await self._openai.aclose()
        await self.sarvam.close()
