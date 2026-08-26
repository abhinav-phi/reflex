"""Settings via pydantic-settings (Rules §15.1: config via env only)."""

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IST = "Asia/Kolkata"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Database — host port 15432 (compose maps 15432->5432 to dodge Windows
    # excluded-port ranges; see docker-compose.yml + MANUAL_STEPS.md §10)
    database_url: str = "postgresql+psycopg://reflex_agent:agent_dev_pw@localhost:15432/reflex"
    database_url_admin: str = "postgresql+psycopg://postgres:reflex_dev_pg@localhost:15432/reflex"
    database_url_eval: str = "postgresql+psycopg://reflex_eval:eval_dev_pw@localhost:15432/reflex"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_hours: int = 8

    # Razorpay — TEST MODE ONLY (Rules §1.7)
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = "dev-webhook-secret"

    # LLM (OpenAI-compatible). Empty key ⇒ system runs degraded/cached end-to-end.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # Runtime
    timezone: str = IST
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @model_validator(mode="after")
    def _cloud_db_fallback(self):  # type: ignore[no-untyped-def]
        # Antideploy cloud only auto-provides DATABASE_URL (single) - reuse it for ADMIN/EVAL if they are still localhost defaults
        # This keeps local compose (15432) working but makes cloud single-DB deploys pass alembic upgrade
        if "DATABASE_URL" in os.environ and os.environ["DATABASE_URL"]:
            cloud_url = os.environ["DATABASE_URL"]
            # If ADMIN/EVAL were not explicitly set in env, inherit from DATABASE_URL
            if "DATABASE_URL_ADMIN" not in os.environ:
                object.__setattr__(self, "database_url_admin", cloud_url)  # type: ignore[attr-defined]
            if "DATABASE_URL_EVAL" not in os.environ:
                object.__setattr__(self, "database_url_eval", cloud_url)  # type: ignore[attr-defined]
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
