import asyncio
import base64
import logging
import random
from typing import Any

import httpx

from app.config import Settings
from app.providers.errors import ProviderUnavailable
from app.providers.ratelimit import TokenBucket

log = logging.getLogger(__name__)

SARVAM_URL = "https://api.sarvam.ai"
TIMEOUT_S = 45
BACKOFF_S = (1, 2, 4)
RETRYABLE = {429, 500, 502, 503, 504}
CALLS_PER_SECOND = 1
LANGUAGE_CODES = {"hi": "hi-IN", "bn": "bn-IN", "mr": "mr-IN", "en": "en-IN"}


class Sarvam:
    """Translation and speech. Each API has its own rate limit, and credit running out is final."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=SARVAM_URL,
            headers={"api-subscription-key": settings.sarvam_api_key},
            timeout=TIMEOUT_S,
        )
        self._buckets = {path: TokenBucket(CALLS_PER_SECOND) for path in ("translate", "tts", "stt")}
        self.out_of_credit = False

    async def _post(self, bucket: str, path: str, **request: Any) -> dict[str, Any]:
        if not self._settings.sarvam_api_key:
            raise ProviderUnavailable("no Sarvam key")
        if self.out_of_credit:
            raise ProviderUnavailable("out of credit")
        failure = "no attempt made"
        for delay in (*BACKOFF_S, None):
            await self._buckets[bucket].acquire()
            try:
                response = await self._client.post(path, **request)
                if response.status_code == 200:
                    return response.json()
                failure = f"status {response.status_code}"
                if response.status_code == 402:
                    self.out_of_credit = True
                    break
                if response.status_code not in RETRYABLE:
                    break
            except (httpx.HTTPError, ValueError) as exc:
                failure = type(exc).__name__
            if delay is not None:
                await asyncio.sleep(delay + random.random())
        # Only the status: the request holds what a citizen said.
        log.warning("Sarvam %s failed: %s", bucket, failure)
        raise ProviderUnavailable(failure)

    async def translate(self, text: str, language: str) -> str:
        result = await self._post(
            "translate",
            "/translate",
            json={
                "input": text,
                "source_language_code": "en-IN",
                "target_language_code": LANGUAGE_CODES[language],
                "model": self._settings.translate_model,
                "numerals_format": "international",
            },
        )
        translated = result.get("translated_text")
        if not isinstance(translated, str) or not translated.strip():
            raise ProviderUnavailable("unusable reply: no translation")
        return translated.strip()

    async def tts(self, text: str, language: str) -> bytes:
        result = await self._post(
            "tts",
            "/text-to-speech",
            json={
                "text": text,
                "language_code": LANGUAGE_CODES[language],
                "model": self._settings.tts_model,
                "speaker": self._settings.voice_for(language),
                "output_audio_codec": "mp3",
            },
        )
        try:
            return base64.b64decode(result["audios"][0], validate=True)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"unusable reply: {type(exc).__name__}") from exc

    async def stt(self, audio: bytes, content_type: str, language: str) -> tuple[str, float | None]:
        """The transcript, and how sure Sarvam is of the language. Neither is stored or logged.

        The run's language is sent because detecting it from a word or two, such as "हाँ", is
        what short answers are worst at.
        """
        result = await self._post(
            "stt",
            "/speech-to-text",
            files={"file": ("answer", audio, content_type)},
            data={"model": self._settings.stt_model, "language_code": LANGUAGE_CODES[language]},
        )
        return str(result.get("transcript") or "").strip(), result.get("language_probability")

    async def close(self) -> None:
        await self._client.aclose()
