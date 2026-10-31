import asyncio

from app.claims.schemas import EntailmentResult, EntailmentVerdict, ExtractionResult, TriageResult
from app.providers.gateway import ProviderUnavailable


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


class FakeGateway:
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.ocr_calls = 0
        self.embed_calls = 0
        self.ocr_failures = 0
        self.embed_fails = False
        self.prompts: dict[str, list[str]] = {}
        # A test sets these. Each entry is a reply, or an exception to raise.
        self.replies: dict[str, list] = {"triage": [], "extract": [], "repair": [], "entail": []}
        self.entail_label = "ENTAILED"
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
        if self.embed_fails:
            raise ProviderUnavailable("status 503")
        return [[0.1] * self.dim for _ in texts]

    async def close(self) -> None:
        pass
