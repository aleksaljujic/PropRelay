from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "propflow"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = (
        "postgresql+asyncpg://propflow:propflow@localhost:5432/propflow"
    )
    database_pool_size: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # WhatsApp Meta Cloud API
    meta_whatsapp_token: str = ""
    meta_phone_number_id: str = ""
    meta_webhook_verify_token: str = "propflow-dev-verify-token"
    meta_api_version: str = "v23.0"

    # Middleware smoke test — remove once real agent router is wired
    # Tenant number is NOT needed — it comes from the webhook "from" field automatically
    # E.164 digits only, no "+"
    test_landlord_phone: str = ""

    # Anthropic Claude API
    # anthropic_model_smart → Vision AI diagnosis and complex reasoning (Sonnet)
    # anthropic_model_fast  → intent classification and simple responses (Haiku)
    anthropic_api_key: str = ""
    anthropic_model_smart: str = "claude-sonnet-4-20250514"
    anthropic_model_fast: str = "claude-haiku-4-5-20251001"
    llm_max_retries: int = 3

    # Orchestration timeouts (seconds)
    timeout_photo_reminder_seconds: int = 86_400  # 24 h
    timeout_landlord_escalation_seconds: int = 1_800  # 30 min
    timeout_contractor_confirm_seconds: int = 900  # 15 min
    timeout_worker_poll_seconds: float = 5.0

    # Sentry (optional)
    sentry_dsn: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
