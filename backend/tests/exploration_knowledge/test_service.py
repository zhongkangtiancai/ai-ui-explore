"""Boundary tests for process-local unified knowledge exports."""

from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration_knowledge.models import (
    ComparisonKnowledgeSource,
    TaskKnowledgeSource,
)
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityRunState,
    PermissionComparisonResult,
)
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
    assert "runtime" not in source.model_dump_json()
    assert service.knowledge_source("task-999") is None


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
