import pytest
from pydantic import ValidationError

from ai_ui_explorer.core.config import Settings


def test_settings_reject_invalid_environment_without_leaking_secret() -> None:
    secret = "do-not-print-this-secret"

    with pytest.raises(ValidationError) as error:
        Settings(
            environment="invalid",  # type: ignore[arg-type]
            database_url="postgresql://user:password@localhost:5432/explorer",
            llm_api_key=secret,
        )

    assert secret not in str(error.value)


def test_settings_use_safe_development_defaults() -> None:
    settings = Settings(database_url="postgresql://user:password@localhost:5432/explorer")

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.llm_api_key is None
    assert str(settings.database_url).startswith("postgresql://")
