"""Deterministic orchestration tests for managed exploration tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from time import monotonic, sleep

import pytest

from ai_ui_explorer.exploration.authentication import (
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration.task import ExplorationTask
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import (
    CreateExplorationTaskCommand,
    ExplorationTaskService,
    TaskServiceError,
)


@dataclass(frozen=True)
class _FakeRunResult:
    status: str
    visit_count: int


class _FakeLoginRuntime:
    def __init__(self, task: ExplorationTask, *, authenticated: bool = True) -> None:
        self._task = task
        self._authenticated = authenticated
        self.closed = False
        self.start_calls = 0
        self.confirm_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self._task.start_collection()
        self._task.pause_for_human(reason_code="authentication_required")

    def confirm_and_verify(self) -> AuthenticationVerification:
        self.confirm_calls += 1
        self._task.confirm_human_ready()
        if not self._authenticated:
            self._task.record_authentication_result(
                authenticated=False,
                checkpoint_id=None,
            )
            return AuthenticationVerification(
                authenticated=False,
                reason_code="checkpoint_not_verified",
                checkpoint_id=None,
            )
        self._task.record_authentication_result(
            authenticated=True,
            checkpoint_id="configured_post_login_checkpoint",
        )
        return AuthenticationVerification(
            authenticated=True,
            reason_code="verified",
            checkpoint_id="configured_post_login_checkpoint",
        )

    def collector_port(self) -> object:
        return object()

    def close(self) -> None:
        self.closed = True


class _FakeRunner:
    def __init__(
        self,
        task: ExplorationTask,
        *,
        started: Event | None = None,
        unblock: Event | None = None,
        error: Exception | None = None,
    ) -> None:
        self._task = task
        self._started = started
        self._unblock = unblock
        self._error = error
        self.calls = 0

    def run(self, *, modules: list[ModuleEntry]) -> _FakeRunResult:
        self.calls += 1
        assert modules == [ModuleEntry(module_id="dashboard", url="https://app.example.test/dashboard")]
        if self._started is not None:
            self._started.set()
        if self._unblock is not None:
            assert self._unblock.wait(timeout=2)
        if self._error is not None:
            raise self._error
        self._task.complete()
        return _FakeRunResult(status="completed", visit_count=1)


class _Fakes:
    def __init__(
        self,
        *,
        authenticated: bool = True,
        runner_error: Exception | None = None,
        block_runner: bool = False,
    ) -> None:
        self.authenticated = authenticated
        self.runner_error = runner_error
        self.started = Event()
        self.unblock = Event() if block_runner else None
        self.runtime: _FakeLoginRuntime | None = None
        self.runner: _FakeRunner | None = None

    def runtime_factory(
        self,
        task: ExplorationTask,
        _plan: AuthenticationPlan,
        _policy: object,
    ) -> _FakeLoginRuntime:
        self.runtime = _FakeLoginRuntime(task, authenticated=self.authenticated)
        return self.runtime

    def runner_factory(
        self,
        _policy: object,
        _budget: ExplorationBudget,
        _collector: object,
        task: ExplorationTask,
    ) -> _FakeRunner:
        self.runner = _FakeRunner(
            task,
            started=self.started,
            unblock=self.unblock,
            error=self.runner_error,
        )
        return self.runner


def _command(*, with_login: bool = True) -> CreateExplorationTaskCommand:
    return CreateExplorationTaskCommand(
        module_entry=ModuleEntry(
            module_id="dashboard",
            url="https://app.example.test/dashboard",
        ),
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        authentication_plan=(
            AuthenticationPlan(
                authentication_url="https://sso.example.test/login",
                post_login_url_prefix="https://app.example.test/dashboard",
                checkpoint_css_selector="#signed-in-marker",
            )
            if with_login
            else None
        ),
    )


def _service(fakes: _Fakes) -> ExplorationTaskService:
    return ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=fakes.runtime_factory,
        runner_factory=fakes.runner_factory,
    )


def _wait_for(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("background task did not reach the expected state")


def test_login_task_pauses_until_explicit_confirmation() -> None:
    fakes = _Fakes()
    service = _service(fakes)

    task = service.create(_command())

    assert task.state == "paused_for_human"
    assert fakes.runner is None

    confirmed = service.confirm_login(task.task_id)

    assert confirmed.state in {"collecting", "completed"}
    _wait_for(lambda: service.get(task.task_id).state == "completed")  # type: ignore[union-attr]
    assert fakes.runner is not None
    assert fakes.runner.calls == 1


def test_cancel_closes_runtime_and_returns_cancelled() -> None:
    fakes = _Fakes()
    service = _service(fakes)
    task = service.create(_command())

    cancelled = service.cancel(task.task_id)

    assert cancelled.state == "cancelled"
    assert fakes.runtime is not None
    assert fakes.runtime.closed is True
    assert service.cancel(task.task_id).state == "cancelled"


def test_unknown_task_returns_none_for_read_operations() -> None:
    service = _service(_Fakes())

    assert service.get("task-999") is None
    assert service.events("task-999") is None
    assert service.result("task-999") is None


def test_failed_authentication_remains_paused_without_starting_runner() -> None:
    fakes = _Fakes(authenticated=False)
    service = _service(fakes)
    task = service.create(_command())

    confirmed = service.confirm_login(task.task_id)

    assert confirmed.state == "paused_for_human"
    assert fakes.runner is None


def test_runner_exception_ends_task_with_fixed_failure_reason() -> None:
    fakes = _Fakes(runner_error=RuntimeError("token=should-not-leak"))
    service = _service(fakes)
    task = service.create(_command(with_login=False))

    _wait_for(lambda: service.get(task.task_id).state == "failed")  # type: ignore[union-attr]
    events = service.events(task.task_id)

    assert events is not None
    assert events[-1].reason_code == "runner_failure"
    assert "should-not-leak" not in service.get(task.task_id).model_dump_json()  # type: ignore[union-attr]


def test_login_runtime_factory_failure_ends_task_without_leaking_detail() -> None:
    fakes = _Fakes()

    def fail_runtime(
        _task: ExplorationTask,
        _plan: AuthenticationPlan,
        _policy: object,
    ) -> _FakeLoginRuntime:
        raise RuntimeError("cookie=should-not-leak")

    service = ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=fail_runtime,
        runner_factory=fakes.runner_factory,
    )

    task = service.create(_command())

    assert task.state == "failed"
    assert task.events[-1].reason_code == "login_runtime_error"
    assert "should-not-leak" not in task.model_dump_json()


def test_terminal_task_rejects_login_confirmation() -> None:
    fakes = _Fakes()
    service = _service(fakes)
    task = service.create(_command())
    service.cancel(task.task_id)

    with pytest.raises(TaskServiceError, match=r"^Task cannot confirm login\.$"):
        service.confirm_login(task.task_id)
