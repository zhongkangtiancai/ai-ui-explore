from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_UI_EXPLORER_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "enterprise-test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]
    llm_provider: Literal["mock", "openai", "deepseek", "compatible"] = "mock"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
