import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from ai_ui_explorer.core.config import Settings
from ai_ui_explorer.persistence.database import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    create_database_engine,
    verify_database_connection,
)


def test_settings_require_postgresql_database_url() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_settings_reject_non_postgresql_database_url() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(database_url="sqlite:///local.db")


def test_database_connection_failure_uses_fixed_safe_error() -> None:
    engine = create_engine(
        "postgresql+psycopg://user:secret@127.0.0.1:1/explorer?connect_timeout=1"
    )

    with pytest.raises(DatabaseConnectionError, match="Database connection unavailable") as error:
        verify_database_connection(engine)

    assert "secret" not in str(error.value)
    assert "127.0.0.1" not in str(error.value)


def test_database_engine_rejects_non_postgresql_url() -> None:
    with pytest.raises(DatabaseConfigurationError, match="PostgreSQL database URL required"):
        create_database_engine("sqlite:///local.db")
