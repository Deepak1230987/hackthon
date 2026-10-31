from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.acquisition.storage import Storage, SupabaseStorage
from app.api import documents, errors, health, library, runs
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.graph.build import build_graph
from app.graph.deps import Deps
from app.graph.events import EventStore
from app.graph.runner import RunRunner
from app.providers.gateway import Gateway


@dataclass
class Services:
    settings: Settings
    deps: Deps
    runner: RunRunner


def create_app(
    settings: Settings | None = None,
    storage: Storage | None = None,
    gateway: Gateway | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        store = storage or SupabaseStorage(settings)
        providers = gateway or Gateway(settings)
        deps = Deps(settings, sessions, EventStore(sessions), store, providers)
        # autocommit and no prepared statements, as required by the checkpointer and pooler.
        pool = AsyncConnectionPool(
            settings.conninfo,
            open=False,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
        )
        await pool.open()
        try:
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            runner = RunRunner(build_graph(deps, checkpointer), deps)
            app.state.services = Services(settings, deps, runner)
            await runner.recover()
            yield
            await runner.shutdown()
        finally:
            await pool.close()
            await store.close()
            await providers.close()
            await engine.dispose()

    app = FastAPI(title="Haq", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    errors.register(app)
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(runs.router)
    app.include_router(library.router)
    return app
