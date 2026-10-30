import asyncio


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
