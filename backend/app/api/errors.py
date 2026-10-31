import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        action: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.action = action
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "details": self.details,
        }


def register(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def on_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.body()}, status_code=exc.status)

    @app.exception_handler(OperationalError)
    async def on_database_error(_: Request, exc: OperationalError) -> JSONResponse:
        log.warning("Database unavailable: %s", type(exc.orig).__name__)
        error = ApiError(
            "DATABASE_UNAVAILABLE", "We can't reach our database. Try again soon.", action="retry"
        )
        return JSONResponse({"error": error.body()}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        error = ApiError("INVALID_REQUEST", "The request is not valid.", details={"fields": fields})
        return JSONResponse({"error": error.body()}, status_code=400)
