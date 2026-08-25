"""Opt-in PostgreSQL migration acceptance tests for safe persistence."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import create_engine, inspect

from ai_ui_explorer.core.config import get_settings
from ai_ui_explorer.exploration.authentication import AuthenticationPlan, AuthenticationVerification
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.permission_comparison.service import PermissionComparisonView
from ai_ui_explorer.persistence.database import create_database_engine, create_session_factory
from ai_ui_explorer.persistence.repositories import SafeTaskRepository
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport
from ai_ui_explorer.task_management.models import TaskEventView, TaskResultSummary, TaskSummary
from ai_ui_explorer.task_management.persistence import PersistentTaskProjectionStore
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import (
    CreateExplorationTaskCommand,
    ExplorationTaskService,
)
from alembic import command
from alembic.config import Config
from tests.snapshot.conftest import LoginSite

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_TABLES = {
    "exploration_tasks",
    "task_evidence_exports",
    "task_workflows",
    "permission_comparisons",
    "exploration_knowledge_sources",
}


@pytest.fixture(scope="session")
def isolated_database_url() -> str:
    """Require an explicit, separately provisioned PostgreSQL test database."""
    database_url = os.environ.get("AI_UI_EXPLORER_TEST_DATABASE_URL")
    enabled = os.environ.get("AI_UI_EXPLORER_RUN_DATABASE_INTEGRATION_TESTS")
    if not database_url or enabled != "1":
        pytest.skip(
            "set AI_UI_EXPLORER_TEST_DATABASE_URL and "
            "AI_UI_EXPLORER_RUN_DATABASE_INTEGRATION_TESTS=1 to run PostgreSQL acceptance"
        )
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AI_UI_EXPLORER_TEST_DATABASE_URL must use PostgreSQL")
    return database_url


def test_safe_persistence_migration_creates_only_expected_projection_tables(
    isolated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply the migration only to the opt-in test database and inspect its schema."""
    monkeypatch.setenv("AI_UI_EXPLORER_DATABASE_URL", isolated_database_url)
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    try:
        command.upgrade(config, "head")
        engine = create_engine(isolated_database_url)
        try:
            table_names = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    assert _EXPECTED_TABLES <= table_names


def test_terminal_task_projection_is_readable_from_a_rebuilt_repository(
    isolated_database_url: str,
) -> None:
    """A new repository instance can read a persisted safe terminal projection."""
    timestamp = datetime(2026, 8, 20, tzinfo=UTC)
    summary = TaskSummary(
        task_id="task-987654321",
        state="completed",
        phase="completed",
        created_at=timestamp,
        updated_at=timestamp,
        redaction_count=0,
        events=[TaskEventView(event_type="task_completed", occurred_at=timestamp)],
        result=TaskResultSummary(
            page_count=0,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
    )
    engine = create_database_engine(isolated_database_url)
    session_factory = create_session_factory(engine)
    try:
        writer = SafeTaskRepository(session_factory=session_factory)
        writer.persist_terminal_task(
            summary=summary,
            evidence=ExplorationEvidenceExport(
                schema_version="1.0",
                task_id=summary.task_id,
                state="completed",
                result=summary.result,
            ),
            workflow=TaskWorkflowExport(task_id=summary.task_id, state="completed"),
        )

        reader = SafeTaskRepository(session_factory=session_factory)
        assert reader.get_terminal_task_summary(summary.task_id) == summary
        assert reader.get_terminal_task_evidence_export(summary.task_id) is not None
        assert reader.get_terminal_task_workflow(summary.task_id) is not None
    finally:
        engine.dispose()


def test_rebuilt_repository_safely_interrupts_a_live_comparison(
    isolated_database_url: str,
) -> None:
    """Restart recovery fails a live comparison without a result or runtime continuation."""
    timestamp = datetime(2026, 8, 20, tzinfo=UTC)
    comparison_id = "comparison-987654321"
    engine = create_database_engine(isolated_database_url)
    session_factory = create_session_factory(engine)
    try:
        writer = SafeTaskRepository(session_factory=session_factory)
        writer.persist_comparison_view(
            view=PermissionComparisonView(
                comparison_id=comparison_id,
                state="paused_for_human",
                identities={
                    "identity-1": "paused_for_human",
                    "identity-2": "created",
                },
            ),
            created_at=timestamp,
            updated_at=timestamp,
            identity_labels={"identity-1": "管理员", "identity-2": "普通用户"},
        )

        restarted = SafeTaskRepository(session_factory=session_factory)
        assert restarted.interrupt_nonterminal_comparisons(occurred_at=timestamp) == [comparison_id]

        reader = SafeTaskRepository(session_factory=session_factory)
        assert reader.get_terminal_comparison_view(comparison_id) == PermissionComparisonView(
            comparison_id=comparison_id,
            state="failed",
            identities={"identity-1": "failed", "identity-2": "failed"},
            result=None,
        )
    finally:
        engine.dispose()


def test_rebuilt_repository_safely_interrupts_a_live_task(
    isolated_database_url: str,
) -> None:
    """Restart recovery records a safe terminal event without resuming browser work."""
    timestamp = datetime(2026, 8, 20, tzinfo=UTC)
    task_id = "task-987654322"
    initial = TaskSummary(
        task_id=task_id,
        state="paused_for_human",
        phase="awaiting_human",
        created_at=timestamp,
        updated_at=timestamp,
        redaction_count=0,
        events=[
            TaskEventView(event_type="task_created", occurred_at=timestamp),
            TaskEventView(
                event_type="paused_for_human",
                reason_code="authentication_required",
                occurred_at=timestamp,
            ),
        ],
        result=TaskResultSummary(
            page_count=0,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
    )
    engine = create_database_engine(isolated_database_url)
    session_factory = create_session_factory(engine)
    try:
        SafeTaskRepository(session_factory=session_factory).persist_task_summary(initial)

        restarted = SafeTaskRepository(session_factory=session_factory)
        assert restarted.interrupt_nonterminal_tasks(occurred_at=timestamp) == [task_id]

        recovered = SafeTaskRepository(session_factory=session_factory).get_terminal_task_summary(
            task_id
        )
        assert recovered is not None
        assert recovered.state == "failed"
        assert recovered.phase == "interrupted"
        assert recovered.events[-1].event_type == "process_restarted"
        assert recovered.events[-1].reason_code == "process_restarted"
    finally:
        engine.dispose()


def test_real_chromium_terminal_task_is_readable_after_service_rebuild(
    isolated_database_url: str,
    login_site: LoginSite,
) -> None:
    """A completed local-browser task is read from PostgreSQL without creating a runtime."""
    runtime_closed = Event()
    runtime_error_types: list[str] = []
    engine = create_database_engine(isolated_database_url)
    session_factory = create_session_factory(engine)
    repository = SafeTaskRepository(session_factory=session_factory)
    projection_store = PersistentTaskProjectionStore(repository=repository)

    class SimulatedHumanRuntime:
        def __init__(self, delegate: object) -> None:
            self._delegate = delegate

        def start(self) -> None:
            try:
                self._delegate.start()  # type: ignore[attr-defined]
                browser = object.__getattribute__(self._delegate, "_browser")
                page = object.__getattribute__(browser, "_page")
                page.locator("#fixture-login").click()
            except Exception as error:
                runtime_error_types.append(type(error).__name__)
                raise

        def confirm_and_verify(self) -> AuthenticationVerification:
            return self._delegate.confirm_and_verify()  # type: ignore[attr-defined]

        def collector_port(self) -> object:
            return self._delegate.collector_port()  # type: ignore[attr-defined]

        def close(self) -> None:
            self._delegate.close()  # type: ignore[attr-defined]
            runtime_closed.set()

    def runtime_factory(context: object, plan: AuthenticationPlan, policy: object) -> object:
        browser = PlaywrightBrowserSession.open(headless=False)
        collector = context.create_session_collector(  # type: ignore[attr-defined]
            session=browser,
            limits=SnapshotLimits(),
        )
        runtime = context.create_human_login_session(  # type: ignore[attr-defined]
            plan=plan,
            policy=policy,
            browser=browser,
            collector=collector,
        )
        return SimulatedHumanRuntime(runtime)

    def runner_factory(*args: object) -> object:
        return args[0].create_runner(  # type: ignore[attr-defined]
            policy=args[1],
            budget=args[2],
            collector=args[3],
            cancellation_token=args[4],
        )

    def never_start_runtime(*_args: object) -> object:
        raise AssertionError("restart read must not create a browser runtime")

    def never_start_runner(*_args: object) -> object:
        raise AssertionError("restart read must not create a runner")

    service = ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=runtime_factory,  # type: ignore[arg-type]
        runner_factory=runner_factory,  # type: ignore[arg-type]
        task_summary_writer=repository.persist_task_summary,
        terminal_projection_writer=lambda summary, collector: projection_store.persist_terminal(
            summary=summary,
            collector=collector,
        ),
    )
    try:
        task = service.create(
            CreateExplorationTaskCommand(
                module_entry=ModuleEntry(module_id="dashboard", url=login_site.dashboard_url),
                allowed_origins=[login_site.policy.allowed_origins[0]],
                authentication_origins=[login_site.policy.authentication_origins[0]],
                budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
                authentication_plan=AuthenticationPlan(
                    authentication_url=login_site.login_url,
                    post_login_url_prefix=login_site.dashboard_url,
                    checkpoint_css_selector="#signed-in-marker",
                ),
                allow_local_http=True,
            )
        )
        _wait_for(
            lambda: service.get(task.task_id).state  # type: ignore[union-attr]
            in {"paused_for_human", "failed", "cancelled"},
            timeout_seconds=30,
        )
        started = service.get(task.task_id)
        assert started is not None
        assert started.state == "paused_for_human", {
            "summary": started.model_dump(mode="json"),
            "runtime_error_types": runtime_error_types,
        }
        service.confirm_login(task.task_id)
        _wait_for(lambda: service.get(task.task_id).state == "completed")  # type: ignore[union-attr]
        assert runtime_closed.wait(timeout=2)

        rebuilt = ExplorationTaskService(
            registry=ExplorationTaskRegistry(),
            runtime_factory=never_start_runtime,  # type: ignore[arg-type]
            runner_factory=never_start_runner,  # type: ignore[arg-type]
            terminal_summary_reader=repository.get_terminal_task_summary,
            terminal_export_reader=repository.get_terminal_task_evidence_export,
            terminal_workflow_reader=repository.get_terminal_task_workflow,
        )
        restored = rebuilt.get(task.task_id)
        assert restored is not None
        assert restored.state == "completed"
        assert rebuilt.export(task.task_id) is not None
        assert rebuilt.workflow(task.task_id) is not None
    finally:
        engine.dispose()


def _wait_for(predicate: Callable[[], bool], *, timeout_seconds: float = 5) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("background task did not reach the expected state")
