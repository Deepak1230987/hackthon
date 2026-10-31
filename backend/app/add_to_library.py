"""Add a real document to the library by sending it through the running pipeline.

    uv run python -m app.add_to_library <pdf-url> --title "Scheme guidelines"
"""

import argparse
import asyncio
import time
import uuid

import httpx
from sqlalchemy import update

from app.config import get_settings
from app.db.models import Document
from app.db.session import create_engine, create_session_factory

POLL_S = 2
MAX_WAIT_S = 240


def run_pipeline(api: str, url: str, language: str) -> dict:
    response = httpx.post(f"{api}/v1/documents", json={"url": url, "language": language}, timeout=30)
    response.raise_for_status()
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + MAX_WAIT_S
    while time.monotonic() < deadline:
        view = httpx.get(f"{api}/v1/runs/{run_id}", timeout=30).json()
        if view["status"] in ("completed", "partial", "failed"):
            return view
        time.sleep(POLL_S)
    raise SystemExit(f"Run {run_id} didn't finish in {MAX_WAIT_S} seconds.")


async def mark_in_library(document_id: str, title: str) -> None:
    engine = create_engine(get_settings())
    try:
        async with create_session_factory(engine)() as session:
            await session.execute(
                update(Document)
                .where(Document.id == uuid.UUID(document_id))
                .values(in_library=True, title=title)
            )
            await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--title", required=True)
    parser.add_argument("--language", default="hi")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()

    view = run_pipeline(args.api, args.url, args.language)
    if view["status"] != "completed":
        raise SystemExit(f"Not added. Run ended as {view['status']}: {view['error']}")
    asyncio.run(
        mark_in_library(view["document"]["id"], args.title),
        loop_factory=asyncio.SelectorEventLoop,
    )
    print(f"Added {view['document']['id']}: {args.title}")


if __name__ == "__main__":
    main()
