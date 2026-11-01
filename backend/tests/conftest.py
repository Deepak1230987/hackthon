import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pymupdf
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from app.config import Settings
from app.main import create_app
from tests.fakes import FakeGateway, FakeStorage

BACKEND = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def event_loop_policy():
    # psycopg's async mode can't use the Windows default (proactor) loop.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


def make_pdf(text_content: str = "A test page", password: str | None = None) -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text_content)
    if password:
        return document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password
        )
    return document.tobytes()


def make_scanned_pdf(seed: int = 0, pages: int = 1) -> bytes:
    """Pages holding only an image, like a scan."""
    document = pymupdf.open()
    for number in range(pages):
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pixmap.set_rect(pixmap.irect, (seed % 255, number % 255, 200))
        document.new_page().insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=pixmap)
    return document.tobytes()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "EMBEDDING_DIM": "768"}
    url = TEST_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True
    )
    return TEST_DATABASE_URL


@pytest.fixture
def settings(migrated_database: str, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=migrated_database,
        upload_dir=tmp_path,
        max_pdf_mb=1,
        embedding_dim=768,
        # Every test shares one client address. The limit has its own tests.
        max_runs_per_ip=100_000,
    )


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest_asyncio.fixture
async def app(settings: Settings, storage: FakeStorage, gateway: FakeGateway):
    application = create_app(settings, storage, gateway)
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
