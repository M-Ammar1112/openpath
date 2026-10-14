"""Application configuration via environment variables (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment-driven settings. See `.env.example` for all options."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend
    openpath_env: str = "development"
    openpath_host: str = "127.0.0.1"
    openpath_port: int = 8000
    openpath_log_level: str = "INFO"
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'openpath.db'}"

    # Frontend (informational for scripts)
    vite_port: int = 5173

    # Data acquisition
    crawler_user_agent: str = "OpenPathBot/1.0 (+https://github.com/M-Ammar1112/openpath)"
    crawler_timeout_seconds: float = 20.0
    crawler_rate_limit_seconds: float = 2.0
    crawler_respect_robots: bool = True
    crawler_cache_ttl_hours: float = 12.0

    # Scheduler
    refresh_interval_seconds: int = 3600
    freshness_sweep_interval_seconds: int = 1800
    watchlist_check_interval_seconds: int = 1800
    scheduler_enabled: bool = True

    # CORS
    backend_cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # Optional API keys (never hard-code)
    crossref_api_key: str | None = None
    serp_api_key: str | None = None

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow a comma-separated string as well as a JSON list."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return None  # let pydantic parse the JSON list
            return [part.strip() for part in text.split(",") if part.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.openpath_env.lower() == "production"

    @property
    def data_dir(self) -> Path:
        return REPO_ROOT / "data"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()