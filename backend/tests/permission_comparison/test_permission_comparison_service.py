"""Tests for serial, process-local permission comparison orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any

from ai_ui_explorer.exploration.authentication import AuthenticationPlan
from ai_ui_explorer.exploration.queue import ExplorationBudget, ExplorationTarget, ModuleEntry
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityProfile,
    IdentityRunState,
    PermissionComparisonResult,
)
from ai_ui_explorer.permission_comparison.service import (
    CreatePermissionComparisonCommand,
    PermissionComparisonService,
    PermissionComparisonView,
)
from tests.snapshot.factories import make_element, make_frame, make_snapshot


@dataclass
class _TaskView:
    task_id: str
    state: str


@dataclass
class _ChildExecution:
    identity_id: str
    view: _TaskView
    sink: Any
    terminal_callback: Any
    start_calls: int = 1
    close_calls: int = 0


class _FakeTaskService:
    def __init__(self, *, failed_identity_id: str | None = None) -> None:
        self._failed_identity_id = failed_identity_id
        self.executions: dict[str, _ChildExecution] = {}
        self._next_task_number = 1

    def create(self, command: Any, *, evidence_sink: Any, on_terminal: Any) -> _TaskView:
        identity_id = f"identity-{self._next_task_number}"
        task_id = f"task-{self._next_task_number}"
        self._next_task_number += 1
        view = _TaskView(task_id=task_id, state="paused_for_human")
        self.executions[identity_id] = _ChildExecution(
            identity_id=identity_id,
            view=view,
            sink=evidence_sink,
            terminal_callback=on_terminal,
        )
        return view

    def get(self, task_id: str) -> _TaskView | None:
        return next(
            (
                execution.view
                for execution in self.executions.values()
                if execution.view.task_id == task_id
            ),
            None,
        )

    def confirm_login(self, task_id: str) -> _TaskView:
        execution = next(
            execution
            for execution in self.executions.values()
            if execution.view.task_id == task_id
        )
        if execution.identity_id == self._failed_identity_id:
            execution.view.state = "failed"
        else:
            execution.sink.record(
                ExplorationTarget(
                    url="https://app.example.test/dashboard",
                    depth=0,
                    source_url=None,
                    module_id="dashboard",
                    action_type="module_entry",
                    label="Dashboard",
                ),
                make_snapshot(
                    frames=[
                        make_frame(
                            elements=[
                                make_element(
                                    element_id="dashboard-link",
                                    tag="a",
                                    role="link",
                                    accessible_name="Dashboard",
                                    href="https://app.example.test/dashboard",
                                )
                            ]
                        )
                    ]
                ),
            )
            execution.view.state = "completed"
        execution.close_calls += 1
        execution.terminal_callback(execution.view)
        return execution.view

    def cancel(self, task_id: str) -> _TaskView:
        execution = next(
            execution
            for execution in self.executions.values()
            if execution.view.task_id == task_id
        )
        execution.view.state = "cancelled"
        execution.close_calls += 1
        execution.terminal_callback(execution.view)
        return execution.view


def _command() -> CreatePermissionComparisonCommand:
    return CreatePermissionComparisonCommand(
        module_entry=ModuleEntry(
            module_id="dashboard",
            url="https://app.example.test/dashboard",
        ),
        allowed_origins=["https://app.example.test"],
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        identities=[
            IdentityProfile(
                identity_id="identity-1",
                label="管理员",
                authentication_plan=_authentication_plan(),
            ),
            IdentityProfile(
                identity_id="identity-2",
                label="普通用户",
                authentication_plan=_authentication_plan(),
            ),
        ],
    )


def _authentication_plan() -> AuthenticationPlan:
    return AuthenticationPlan(
        authentication_url="https://sso.example.test/login",
        post_login_url_prefix="https://app.example.test/dashboard",
        checkpoint_css_selector="#signed-in-marker",
    )


def test_service_reads_persisted_terminal_comparison_after_runtime_is_absent() -> None:
    persisted = PermissionComparisonView(
        comparison_id="comparison-99",
        state="completed",
        identities={"identity-1": "completed", "identity-2": "completed"},
        result=PermissionComparisonResult(
            comparison_id="comparison-99",
            status="completed",
            identities=[
                IdentityEvidenceBundle(
                    identity_id="identity-1",
                    state=IdentityRunState.COMPLETED,
                ),
                IdentityEvidenceBundle(
                    identity_id="identity-2",
                    state=IdentityRunState.COMPLETED,
                ),
            ],
        ),
    )
    service = PermissionComparisonService(
        task_service=_FakeTaskService(),
        terminal_view_reader=lambda comparison_id: (
            persisted if comparison_id == "comparison-99" else None
        ),
    )

    assert service.get("comparison-99") == persisted


def test_view_allows_restart_interrupted_comparison_without_conclusion() -> None:
    view = PermissionComparisonView(
        comparison_id="comparison-99",
        state="failed",
        identities={"identity-1": "failed", "identity-2": "created"},
        result=None,
    )

    assert view.state == "failed"
    assert view.result is None


def test_service_lists_persisted_terminal_comparison_after_runtime_is_absent() -> None:
    persisted = PermissionComparisonView(
        comparison_id="comparison-99",
        state="completed",
        identities={"identity-1": "completed", "identity-2": "completed"},
        result=PermissionComparisonResult(
            comparison_id="comparison-99",
            status="completed",
            identities=[
                IdentityEvidenceBundle(
                    identity_id="identity-1",
                    state=IdentityRunState.COMPLETED,
                ),
                IdentityEvidenceBundle(
                    identity_id="identity-2",
                    state=IdentityRunState.COMPLETED,
                ),
            ],
        ),
    )
    service = PermissionComparisonService(
        task_service=_FakeTaskService(),
        terminal_view_list_reader=lambda: [persisted],
    )

    assert service.list_views() == [persisted]


def _wait_for(predicate: Any) -> None:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("comparison did not reach the expected state")


def test_service_runs_identities_serially_and_closes_each_runtime() -> None:
    tasks = _FakeTaskService()
    service = PermissionComparisonService(task_service=tasks)

    comparison = service.create(_command())

    _wait_for(
        lambda: service.get(comparison.comparison_id).identities["identity-1"]
        == "paused_for_human"
    )
    service.confirm_login(comparison.comparison_id, "identity-1")
    _wait_for(
        lambda: service.get(comparison.comparison_id).identities["identity-2"]
        == "paused_for_human"
    )

    assert tasks.executions["identity-1"].close_calls == 1
    assert tasks.executions["identity-2"].start_calls == 1


def test_service_cancellation_stops_current_identity_and_never_starts_next() -> None:
    tasks = _FakeTaskService()
    service = PermissionComparisonService(task_service=tasks)
    comparison = service.create(_command())

    _wait_for(lambda: "identity-1" in tasks.executions)
    service.cancel(comparison.comparison_id)
    _wait_for(lambda: service.get(comparison.comparison_id).state == "cancelled")

    assert "identity-2" not in tasks.executions


def test_failed_identity_keeps_completed_evidence_and_marks_result_partial() -> None:
    tasks = _FakeTaskService(failed_identity_id="identity-2")
    service = PermissionComparisonService(task_service=tasks)
    comparison = service.create(_command())

    _wait_for(
        lambda: service.get(comparison.comparison_id).identities["identity-1"]
        == "paused_for_human"
    )
    service.confirm_login(comparison.comparison_id, "identity-1")
    _wait_for(
        lambda: service.get(comparison.comparison_id).identities["identity-2"]
        == "paused_for_human"
    )
    service.confirm_login(comparison.comparison_id, "identity-2")
    _wait_for(lambda: service.get(comparison.comparison_id).state == "partial")

    result = service.get(comparison.comparison_id).result
    assert result is not None
    assert result.status == "partial"
    assert result.identities[0].pages
    assert all(item.reliability == "inconclusive" for item in result.differences)

    source = service.knowledge_source(comparison.comparison_id)
    assert source is not None
    assert source.source_id == comparison.comparison_id
    assert source.identity_labels["identity-1"] == "管理员"
    assert "authentication_plan" not in source.model_dump_json()
