"""Settings via pydantic-settings (Rules §15.1: config via env only)."""

from functools import lru_cache

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
