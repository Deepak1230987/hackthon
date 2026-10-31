from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.acquisition.storage import Storage
from app.config import Settings
from app.graph.events import EventStore
from app.providers.gateway import Gateway


@dataclass
class Deps:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    events: EventStore
    storage: Storage
    gateway: Gateway


class RunFailed(Exception):
    """A node ending the run with an error the citizen should see."""

    def __init__(
        self,
        code: str,
        message: str,
        action: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.details = details or {}
