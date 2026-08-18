"""Alembic environment for PostgreSQL safe-projection persistence."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from ai_ui_explorer.core.config import get_settings
from ai_ui_explorer.persistence.models import Base
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure_database_url() -> None:
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.database_url.unicode_string())


def run_migrations_offline() -> None:
    _configure_database_url()
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _configure_database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
