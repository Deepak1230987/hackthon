from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db.models import Base

settings = get_settings()
engine = create_engine(
    settings.sqlalchemy_url,
    poolclass=pool.NullPool,
    connect_args={"prepare_threshold": None},
)


def include_name(name, type_, parent_names):
    # LangGraph owns its checkpoint tables, so autogenerate must never drop them.
    return type_ != "table" or name in Base.metadata.tables


with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()
