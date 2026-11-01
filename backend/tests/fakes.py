import asyncio

from app.claims.schemas import EntailmentResult, EntailmentVerdict, ExtractionResult, TriageResult
from app.providers.gateway import ProviderUnavailable
from app.voice.guard import MeaningResult, MeaningVerdict
from app.voice.translate import TranslatedSentence, TranslationResult


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0
        self.hold: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def put(self, path: str, content: bytes, content_type: str) -> None:
        self.put_calls += 1
        self.entered.set()
        if self.hold:
            await self.hold.wait()
        self.objects[path] = content

    async def get(self, path: str) -> bytes:
        return self.objects[path]

    async def close(self) -> None:
        pass


class FakeSarvam:
    def __init__(self) -> None:
        self.out_of_credit = False
        self.translations: dict[str, str] = {}
        self.translate_fails = False
        self.tts_fails = False
        self.translate_calls = 0
        self.tts_calls = 0
        self.stt_reply: tuple[str, float | None] = ("हाँ", 0.9)
        self.stt_fails = False

    async def translate(self, text: str, language: str) -> str:
        self.translate_calls += 1
        if self.translate_fails:
            raise ProviderUnavailable("no Sarvam key")
        return self.translations.get(text, f"अनुवाद: {text}")

    async def tts(self, text: str, language: str) -> bytes:
        self.tts_calls += 1
        if self.tts_fails:
            raise ProviderUnavailable("no Sarvam key")
        return b"mp3:" + text.encode()

    async def stt(self, audio: bytes, content_type: str) -> tuple[str, float | None]:
        if self.stt_fails:
            raise ProviderUnavailable("status 503")
        return self.stt_reply

    async def close(self) -> None:
        pass


class FakeGateway:
    def __init__(self, dim: int = 768) -> None:
        self.sarvam = FakeSarvam()
        self.dim = dim
        self.ocr_calls = 0
        self.embed_calls = 0
        self.ocr_failures = 0
        self.embed_fails = False
        self.embed_hangs = False
        self.prompts: dict[str, list[str]] = {}
        # A test sets these. Each entry is a reply, or an exception to raise.
        self.replies: dict[str, list] = {"triage": [], "extract": [], "repair": [], "entail": []}
        self.entail_label = "ENTAILED"
        self.meaning_label = "SAME"
        self.llm_translation = "एल्एल्एम अनुवाद"
        self.hang_entail_after: int | None = None

    async def structured(self, task, prompt, schema, budget):
        await budget.charge()
        self.prompts.setdefault(task, []).append(prompt)
        if task == "entail" and self.hang_entail_after is not None:
            if len(self.prompts[task]) > self.hang_entail_after:
                await asyncio.sleep(3600)
        if self.replies.get(task):
            reply = self.replies[task].pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        if task == "triage":
            return TriageResult(is_policy=True, reason="A scheme document")
        if task == "extract":
            return ExtractionResult(claims=[])
        if task == "entail":
            count = prompt.count("<claim ")
            return EntailmentResult(
                verdicts=[EntailmentVerdict(index=i, label=self.entail_label) for i in range(count)]
            )
        if task == "meaning":
            count = prompt.count("<pair ")
            return MeaningResult(
                verdicts=[MeaningVerdict(index=i, label=self.meaning_label) for i in range(count)]
            )
        if task == "translate":
            count = prompt.count("<sentence ")
            return TranslationResult(
                translations=[
                    TranslatedSentence(index=i, text=self.llm_translation) for i in range(count)
                ]
            )
        return schema(claims=[])

    async def vision_ocr(self, image: bytes) -> list[dict[str, str]]:
        self.ocr_calls += 1
        if self.ocr_failures > 0:
            self.ocr_failures -= 1
            raise ProviderUnavailable("status 503")
        return [
            {"kind": "heading", "text": "पात्रता"},
            {"kind": "para", "text": f"नियम {self.ocr_calls}: वार्षिक आय 2.5 लाख रुपये से कम होनी चाहिए।"},
            {"kind": "table_row", "text": f"श्रेणी {self.ocr_calls}: सामान्य; राशि: ₹5,000"},
        ]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        if self.embed_hangs:
            await asyncio.sleep(3600)
        if self.embed_fails:
            raise ProviderUnavailable("status 503")
        return [[0.1] * self.dim for _ in texts]

    async def close(self) -> None:
        pass
