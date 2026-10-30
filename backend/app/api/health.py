from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(prefix="/v1")


@router.get("/health")
async def health(request: Request) -> dict:
    services = request.app.state.services
    settings = services.settings
    try:
        async with services.deps.sessions() as session:
            await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "keys_configured": {
            "gemini": bool(settings.gemini_api_key),
            "openai": bool(settings.openai_api_key),
            "sarvam": bool(settings.sarvam_api_key),
            "supabase": bool(settings.supabase_service_key),
        },
    }
