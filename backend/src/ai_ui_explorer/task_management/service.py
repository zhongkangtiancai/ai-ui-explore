"""Background orchestration for process-local controlled exploration tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock, Thread
from typing import Protocol

from pydantic import Field

from ai_ui_explorer.exploration.authentication import (
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration.task import ExplorationTask, ExplorationTaskError
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.task_management.models import (
    ManagedTask,
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry


class TaskServiceError(RuntimeError):
    """Fixed, non-sensitive service error surface."""


class _LoginRuntime(Protocol):
    def start(self) -> None:
        """Open the visible handoff and pause the task."""

    def confirm_and_verify(self) -> AuthenticationVerification:
        """Validate the explicit human login checkpoint."""

    def collector_port(self) -> object:
        """Return the task-bound collector after authentication."""

    def close(self) -> None:
        """Release process-local browser resources."""


class _TaskRunner(Protocol):
    def run(self, *, modules: list[ModuleEntry]) -> object:
        """Execute controlled exploration for the supplied entry module."""


RuntimeFactory = Callable[
    [ExplorationTask, AuthenticationPlan, NavigationPolicy], _LoginRuntime
]
RunnerFactory = Callable[
    [NavigationPolicy, ExplorationBudget, object, ExplorationTask], _TaskRunner
]
CollectorFactory = Callable[[ExplorationTask], object]


class CreateExplorationTaskCommand(DeepFrozenModel):
    """Explicit, policy-bound input for one process-local exploration task."""

    module_entry: ModuleEntry
    allowed_origins: list[str] = Field(min_length=1)
    authentication_origins: list[str] = Field(default_factory=list)
    budget: ExplorationBudget
    authentication_plan: AuthenticationPlan | None = None
    allow_local_http: bool = False


@dataclass
class _TaskExecution:
    task: ExplorationTask
    command: CreateExplorationTaskCommand
    policy: NavigationPolicy
    runtime: _LoginRuntime | None = None


class ExplorationTaskService:
    """Create, observe, cancel, and resume in-memory exploration tasks."""

    def __init__(
        self,
        *,
        registry: ExplorationTaskRegistry,
        runtime_factory: RuntimeFactory,
        runner_factory: RunnerFactory,
        collector_factory: CollectorFactory | None = None,
    ) -> None:
        self._registry = registry
        self._runtime_factory = runtime_factory
        self._runner_factory = runner_factory
        self._collector_factory = collector_factory or _empty_collector
        self._lock = RLock()
        self._executions: dict[str, _TaskExecution] = {}
        self._next_task_number = 1

    def create(self, command: CreateExplorationTaskCommand) -> TaskSummary:
        """Register a task and start it or pause it for explicit human login."""
        policy = NavigationPolicy(
            allowed_origins=list(command.allowed_origins),
            authentication_origins=list(command.authentication_origins),
            allow_local_http=command.allow_local_http,
        )
        task = ExplorationTask.create(task_id=self._allocate_task_id())
        managed = self._registry.create(
            ManagedTask(
                task=task,
                phase="created",
                result=_empty_result(),
                redaction_count=0,
            )
        )
        execution = _TaskExecution(task=task, command=command, policy=policy)
        with self._lock:
            self._executions[task.task_id] = execution
        task_id = task.task_id

        def release_runtime() -> None:
            self._release_runtime(task_id)

        managed.register_terminal_callback(release_runtime)

        if command.authentication_plan is not None:
            self._start_login_task(managed, execution)
            return managed.summary()

        try:
            managed.start_collection()
            managed.set_phase("collecting")
            self._start_runner(managed, execution, self._collector_factory(task))
        except Exception:
            self._fail_collecting_task(managed)
        return managed.summary()

    def get(self, task_id: str) -> TaskSummary | None:
        """Return a safe task summary, or ``None`` after unknown/restarted tasks."""
        managed = self._registry.get(task_id)
        return managed.summary() if managed is not None else None

    def events(self, task_id: str) -> list[TaskEventView] | None:
        """Return only allowlisted audit event fields."""
        summary = self.get(task_id)
        return list(summary.events) if summary is not None else None

    def confirm_login(self, task_id: str) -> TaskSummary:
        """Verify an explicitly completed human login before starting the runner."""
        managed = self._require_managed(task_id)
        if managed.summary().state != "paused_for_human":
            raise TaskServiceError("Task cannot confirm login.")
        execution = self._require_execution(task_id)
        runtime = execution.runtime
        if runtime is None:
            raise TaskServiceError("Task cannot confirm login.")
        try:
            verification = runtime.confirm_and_verify()
        except Exception:
            self._sync_phase(managed)
            raise TaskServiceError("Task cannot confirm login.") from None
        if not verification.authenticated:
            managed.set_phase("awaiting_human")
            return managed.summary()
        try:
            managed.set_phase("collecting")
            self._start_runner(managed, execution, runtime.collector_port())
        except Exception:
            self._fail_collecting_task(managed)
        return managed.summary()

    def cancel(self, task_id: str) -> TaskSummary:
        """Cancel once and trigger registered terminal cleanup; repeated cancel is safe."""
        managed = self._require_managed(task_id)
        if managed.summary().state not in _TERMINAL_STATES:
            try:
                managed.cancel(reason_code="user_cancelled")
            except ExplorationTaskError:
                raise TaskServiceError("Task cannot be cancelled.") from None
            managed.set_phase("cancelled")
        return managed.summary()

    def result(self, task_id: str) -> TaskResultSummary | None:
        """Return only the stored redacted result summary."""
        summary = self.get(task_id)
        return summary.result if summary is not None else None

    def _start_login_task(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
    ) -> None:
        assert execution.command.authentication_plan is not None
        try:
            runtime = self._runtime_factory(
                execution.task,
                execution.command.authentication_plan,
                execution.policy,
            )
            execution.runtime = runtime
            managed.attach_runtime(runtime)
            managed.register_terminal_callback(runtime.close)
            runtime.start()
            managed.set_phase("awaiting_human")
        except Exception:
            self._fail_login_start(managed)

    def _start_runner(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
        collector: object,
    ) -> None:
        runner = self._runner_factory(
            execution.policy,
            execution.command.budget,
            collector,
            execution.task,
        )
        thread = Thread(
            target=self._run_runner,
            args=(managed, execution, runner),
            daemon=True,
            name=f"ai-ui-explorer-{managed.task_id}",
        )
        managed.attach_thread(thread)
        thread.start()

    def _run_runner(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
        runner: _TaskRunner,
    ) -> None:
        try:
            result = runner.run(modules=[execution.command.module_entry])
        except Exception:
            self._fail_collecting_task(managed)
            return
        self._record_run_result(managed, result)
        self._complete_if_runner_did_not_finalize(managed, result)
        self._sync_phase(managed)

    def _record_run_result(self, managed: ManagedTask, result: object) -> None:
        visits = getattr(result, "visits", None)
        visit_count = len(visits) if isinstance(visits, list) else getattr(
            result,
            "visit_count",
            0,
        )
        if not isinstance(visit_count, int) or visit_count < 0:
            visit_count = 0
        managed.set_result(
            TaskResultSummary(
                page_count=visit_count,
                element_count=0,
                link_count=0,
                source_summary="redacted source",
            )
        )

    def _complete_if_runner_did_not_finalize(
        self,
        managed: ManagedTask,
        result: object,
    ) -> None:
        if managed.summary().state != "collecting":
            return
        if getattr(result, "status", None) == "partial":
            managed.mark_partial(reason_code="collector_failure")
        else:
            managed.complete()

    def _fail_collecting_task(self, managed: ManagedTask) -> None:
        if managed.summary().state == "collecting":
            managed.fail(reason_code="runner_failure")
        self._sync_phase(managed)

    def _fail_login_start(self, managed: ManagedTask) -> None:
        if managed.summary().state == "created":
            managed.start_collection()
        if managed.summary().state == "collecting":
            managed.fail(reason_code="login_runtime_error")
        self._sync_phase(managed)

    def _sync_phase(self, managed: ManagedTask) -> None:
        phase = _PHASE_BY_STATE.get(managed.summary().state)
        if phase is not None:
            managed.set_phase(phase)

    def _allocate_task_id(self) -> str:
        with self._lock:
            task_id = f"task-{self._next_task_number}"
            self._next_task_number += 1
            return task_id

    def _require_managed(self, task_id: str) -> ManagedTask:
        managed = self._registry.get(task_id)
        if managed is None:
            raise TaskServiceError("Task was not found.")
        return managed

    def _require_execution(self, task_id: str) -> _TaskExecution:
        with self._lock:
            execution = self._executions.get(task_id)
        if execution is None:
            raise TaskServiceError("Task cannot be resumed.")
        return execution

    def _release_runtime(self, task_id: str) -> None:
        self._registry.remove_runtime(task_id)
        with self._lock:
            self._executions.pop(task_id, None)


_TERMINAL_STATES = frozenset({"completed", "partial", "failed", "cancelled"})
_PHASE_BY_STATE = {
    "created": "created",
    "collecting": "collecting",
    "paused_for_human": "awaiting_human",
    "verifying_authentication": "verifying_authentication",
    "completed": "completed",
    "partial": "partial",
    "failed": "failed",
    "cancelled": "cancelled",
}


def _empty_result() -> TaskResultSummary:
    return TaskResultSummary(
        page_count=0,
        element_count=0,
        link_count=0,
        source_summary="redacted source",
    )


def _empty_collector(_task: ExplorationTask) -> object:
    """Provide no browser state until a production collector is wired by the API."""
    return object()
