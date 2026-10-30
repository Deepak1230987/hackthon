from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    # Prepared statements are off because Supabase's pooler doesn't support them.
    # The session pooler allows 15 clients, so this and the checkpoint pool stay under that.
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
