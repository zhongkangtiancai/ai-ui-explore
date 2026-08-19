"""Explicit test-only dependencies for FastAPI route contract tests."""

from typing import cast
from unittest.mock import Mock

from fastapi import FastAPI

from ai_ui_explorer.core.config import Settings
from ai_ui_explorer.main import create_app
from ai_ui_explorer.task_management.service import ExplorationTaskService


def create_test_app(
    *,
    task_service: object | None = None,
) -> FastAPI:
    """Build an app without a database only through explicit test injection."""
    return create_app(
        settings=Settings(
            database_url="postgresql://user:password@localhost:5432/explorer"
        ),
        task_service=cast(
            ExplorationTaskService,
            task_service
            if task_service is not None
            else Mock(spec=ExplorationTaskService),
        ),
    )
