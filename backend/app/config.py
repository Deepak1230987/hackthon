from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), extra="ignore", env_ignore_empty=True
    )

    database_url: str
    supabase_url: str = ""
    supabase_service_key: str = ""
    storage_bucket: str = "documents"

    gemini_api_key: str = ""
    openai_api_key: str = ""
    sarvam_api_key: str = ""

    llm_primary_model: str = ""
    llm_fallback_model: str = ""
    ocr_model: str = ""
    ocr_fallback_model: str = ""
    embedding_model: str = ""
    embedding_dim: int | None = None
    tts_model: str = "bulbul:v4-flash"
    translate_model: str = "sarvam-translate:v1"
    stt_model: str = "saaras:v4"

    max_concurrent_runs: int = 3
    max_llm_calls: int = 60
    run_timeout_s: int = 180
    max_pdf_mb: int = 50
    max_pages: int = 200
    profile_ttl_s: int = 3600
    cross_provider_verify: bool = False

    allowed_origins: str = "http://localhost:3000"
    upload_dir: Path = Path(".uploads")

    @property
    def sqlalchemy_url(self) -> str:
        return self.conninfo.replace("postgresql://", "postgresql+psycopg://", 1)

    @property
    def conninfo(self) -> str:
        return self.database_url.replace("postgres://", "postgresql://", 1)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
