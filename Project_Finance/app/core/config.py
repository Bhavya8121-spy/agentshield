from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_", env_file=".env", extra="ignore")

    app_name: str = "Finance Forecaster"
    version: str = "0.10.0"
    log_level: str = "INFO"

    max_upload_bytes: int = 10 * 1024 * 1024
    max_rows: int = 250_000
    session_ttl_minutes: int = 180
    max_sessions: int = 250

    classifier_path: str = "app/categorization/model.joblib"
    classifier_min_confidence: float = 0.65
    feedback_path: str = "data/feedback/corrections.jsonl"

    analytics_path: str = "data/analytics/events.jsonl"
    analytics_enabled: bool = True

    forecast_confidence: float = 0.80
    monte_carlo_runs: int = 10_000
    monte_carlo_max_runs: int = 50_000

    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()