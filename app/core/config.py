from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Task Management API"
    database_url: str = "sqlite:///./task_management.db"
    jwt_secret_key: str = Field(
        default="development-only-change-me",
        min_length=16,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:3000"]
    ai_provider: str = "gemini"
    ai_provider_order: list[str] = ["gemini", "groq", "openrouter", "huggingface"]
    ai_max_tasks: int = Field(default=15, ge=1, le=50)
    ai_request_timeout_seconds: int = Field(default=25, ge=5, le=120)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str | None = None
    openrouter_model: str = "openrouter/free"
    huggingface_api_key: str | None = None
    huggingface_model: str = "Qwen/Qwen3-8B"

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg3_driver(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
