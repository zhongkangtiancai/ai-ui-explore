"""Synchronous PostgreSQL connection primitives with a safe error surface."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConnectionError(RuntimeError):
    """Database connectivity failed without exposing connection details."""


class DatabaseConfigurationError(RuntimeError):
    """A persistence configuration violates the PostgreSQL-only boundary."""


def create_database_engine(database_url: str) -> Engine:
    """Create the application's PostgreSQL engine without logging its URL."""
    if not make_url(database_url).drivername.startswith("postgresql"):
        raise DatabaseConfigurationError("PostgreSQL database URL required")
    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build the transaction factory used by persistence repositories."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """Commit one repository operation or roll it back on failure."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def verify_database_connection(engine: Engine) -> None:
    """Check PostgreSQL availability and hide driver-specific failures."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise DatabaseConnectionError("Database connection unavailable") from error
