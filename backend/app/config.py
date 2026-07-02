"""Application settings, loaded from environment (pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    # SQLAlchemy URL. Default targets the compose `db` service.
    database_url: str = "postgresql+psycopg://aigov:changeme-local-only@db:5432/aigov"

    # Comma-separated allowed CORS origins for the SPA.
    api_cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Dev auth (M0–M4). Trust X-Dev-User / X-Dev-Roles headers, seed dev users.
    # MUST be false in production once OIDC (M10) lands.
    dev_auth_enabled: bool = True

    framework_id: str = "nist-ai-rmf-1.0+genai-600-1"

    # Discovery drivers. "stub" = deterministic demo data; "live" = real cloud
    # (read-only). AZURE_SUBSCRIPTION_ID is the fallback subscription when the
    # discovery source's scope isn't a subscription GUID.
    azure_discovery: str = "stub"
    azure_subscription_id: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
