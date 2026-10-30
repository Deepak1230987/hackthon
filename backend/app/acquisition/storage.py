from typing import Protocol

import httpx

from app.config import Settings


class Storage(Protocol):
    async def put(self, path: str, content: bytes, content_type: str) -> None: ...
    async def get(self, path: str) -> bytes: ...
    async def close(self) -> None: ...


class SupabaseStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._client = httpx.AsyncClient(
            base_url=f"{settings.supabase_url.rstrip('/')}/storage/v1",
            headers={"Authorization": f"Bearer {settings.supabase_service_key}"},
            timeout=60,
        )

    async def put(self, path: str, content: bytes, content_type: str) -> None:
        response = await self._client.post(
            f"/object/{self._bucket}/{path}",
            content=content,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        response.raise_for_status()

    async def get(self, path: str) -> bytes:
        response = await self._client.get(f"/object/{self._bucket}/{path}")
        response.raise_for_status()
        return response.content

    async def close(self) -> None:
        await self._client.aclose()
