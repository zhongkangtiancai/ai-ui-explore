"""Boundary tests for process-local unified knowledge exports."""

from datetime import UTC, datetime
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration_knowledge.models import (
    ComparisonKnowledgeSource,
    TaskKnowledgeSource,
)
from ai_ui_explorer.exploration_knowledge.service import (
    ExplorationKnowledgeExportRequest,
    ExplorationKnowledgeExportService,
)
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityRunState,
    PermissionComparisonResult,
)
from ai_ui_explorer.permission_comparison.service import (
    PermissionComparisonService,
    PermissionComparisonView,
)
from ai_ui_explorer.task_management.models import TaskResultSummary, TaskSummary
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import (
    CreateExplorationTaskCommand,
    ExplorationTaskService,
)


def test_export_service_lists_only_safe_terminal_sources() -> None:
    from ai_ui_explorer.exploration_knowledge.service import (
        ExplorationKnowledgeExportService,
    )

    service = ExplorationKnowledgeExportService(
        task_service=_TaskSources(),
        comparison_service=_ComparisonSources(),
    )

    catalog = service.sources()

    assert [item.source_id for item in catalog] == ["comparison-1", "task-1"]
    assert all(item.state in {"completed", "partial", "failed", "cancelled"} for item in catalog)
    assert "authentication_plan" not in catalog[0].model_dump_json()


def test_export_service_rejects_unknown_and_non_terminal_sources_without_runtime_leak() -> None:
    from ai_ui_explorer.exploration_knowledge.service import (
        ExplorationKnowledgeExportError,
        ExplorationKnowledgeExportRequest,
        ExplorationKnowledgeExportService,
    )

    service = ExplorationKnowledgeExportService(
        task_service=_TaskSources(),
        comparison_service=_ComparisonSources(),
    )

    with pytest.raises(ExplorationKnowledgeExportError, match=r"^source unavailable$"):
        service.export(ExplorationKnowledgeExportRequest(task_ids=["task-999"]))
    with pytest.raises(ExplorationKnowledgeExportError, match=r"^source unavailable$"):
        service.export(ExplorationKnowledgeExportRequest(task_ids=["task-2"]))


def test_task_service_projects_only_a_terminal_safe_knowledge_source() -> None:
    class _Runner:
        def run(self, *, modules: list[ModuleEntry]) -> object:
            assert modules[0].module_id == "home"
            return SimpleNamespace(status="completed", visits=[])

    service = ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=lambda *_args: object(),
        runner_factory=lambda *_args: _Runner(),
    )
    task = service.create(
        CreateExplorationTaskCommand(
            module_entry=ModuleEntry(module_id="home", url="https://app.example.test/home"),
            allowed_origins=["https://app.example.test"],
            budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        )
    )

    _wait_for(lambda: service.get(task.task_id).state == "completed")  # type: ignore[union-attr]
    source = service.knowledge_source(task.task_id)

    assert source is not None
    assert source.state == "completed"
    assert source.workflow is not None
    assert source.workflow.task_id == task.task_id
    assert "runtime" not in source.model_dump_json()
    assert service.knowledge_source("task-999") is None


def test_export_service_uses_persisted_task_and_comparison_sources_after_restart() -> None:
    task_source = TaskKnowledgeSource(
        source_id="task-99",
        state="completed",
        pages=[],
    )
    task_summary = TaskSummary(
        task_id="task-99",
        state="completed",
        phase="completed",
        created_at=_timestamp(),
        updated_at=_timestamp(),
        redaction_count=0,
        events=[],
        result=TaskResultSummary(
            page_count=0,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
    )
    comparison_result = PermissionComparisonResult(
        comparison_id="comparison-99",
        status="completed",
        identities=[
            IdentityEvidenceBundle(identity_id="identity-1", state=IdentityRunState.COMPLETED),
            IdentityEvidenceBundle(identity_id="identity-2", state=IdentityRunState.COMPLETED),
        ],
    )
    comparison_source = ComparisonKnowledgeSource(
        source_id="comparison-99",
        result=comparison_result,
        identity_labels={"identity-1": "管理员", "identity-2": "普通用户"},
    )
    task_service = ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=lambda *_args: object(),
        runner_factory=lambda *_args: object(),
        terminal_summary_reader=lambda task_id: task_summary if task_id == "task-99" else None,
        terminal_summary_list_reader=lambda: [task_summary],
        terminal_knowledge_source_reader=lambda task_id: (
            task_source if task_id == "task-99" else None
        ),
    )
    comparison_service = PermissionComparisonService(
        task_service=_TaskSources(),  # type: ignore[arg-type]
        terminal_view_list_reader=lambda: [
            PermissionComparisonView(
                comparison_id="comparison-99",
                state="completed",
                identities={"identity-1": "completed", "identity-2": "completed"},
                result=comparison_result,
            )
        ],
        terminal_knowledge_source_reader=lambda comparison_id: (
            comparison_source if comparison_id == "comparison-99" else None
        ),
    )
    service = ExplorationKnowledgeExportService(
        task_service=task_service,
        comparison_service=comparison_service,
    )

    package = service.export(
        ExplorationKnowledgeExportRequest(
            task_ids=["task-99"],
            comparison_ids=["comparison-99"],
        )
    )

    assert [source.source_id for source in service.sources()] == ["comparison-99", "task-99"]
    assert {source.source_id for source in package.sources} == {"comparison-99", "task-99"}


class _TaskSources:
    def list_summaries(self) -> list[object]:
        return [SimpleNamespace(task_id="task-1"), SimpleNamespace(task_id="task-2")]

    def knowledge_source(self, task_id: str) -> TaskKnowledgeSource | None:
        if task_id == "task-1":
            return TaskKnowledgeSource(
                source_id="task-1",
                state="completed",
                pages=[],
                reason_codes=[],
            )
        return None


class _ComparisonSources:
    def list_views(self) -> list[object]:
        return [SimpleNamespace(comparison_id="comparison-1")]

    def knowledge_source(self, comparison_id: str) -> ComparisonKnowledgeSource | None:
        if comparison_id == "comparison-1":
            return ComparisonKnowledgeSource(
                source_id="comparison-1",
                result=PermissionComparisonResult(
                    comparison_id="comparison-1",
                    status="partial",
                    identities=[
                        IdentityEvidenceBundle(
                            identity_id="identity-1",
                            state=IdentityRunState.COMPLETED,
                        ),
                        IdentityEvidenceBundle(
                            identity_id="identity-2",
                            state=IdentityRunState.PARTIAL,
                        ),
                    ],
                    differences=[],
                ),
            )
        return None


def _wait_for(predicate: object) -> None:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        sleep(0.01)
    raise AssertionError("task did not reach the expected state")


def _timestamp() -> datetime:
    return datetime(2026, 8, 19, tzinfo=UTC)
