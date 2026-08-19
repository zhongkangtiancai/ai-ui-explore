"""Background orchestration for process-local controlled exploration tasks."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Event, RLock, Thread
from typing import Literal, Protocol, cast

from pydantic import Field

from ai_ui_explorer.exploration.authentication import (
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.collector_adapter import (
    SessionSnapshotCollectorAdapter,
    SnapshotCollectorAdapter,
)
from ai_ui_explorer.exploration.interactions import (
    extract_readonly_interaction_candidates,
)
from ai_ui_explorer.exploration.login_runtime import HumanLoginSession
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration.runner import (
    ExplorationCancellationToken,
    ExplorationEvidenceSink,
    ExplorationRunner,
    SnapshotCollectorPort,
)
from ai_ui_explorer.exploration.task import ExplorationTask, ExplorationTaskError
from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.exploration_knowledge.models import TaskKnowledgeSource
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import PageEvidence
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.task_management.evidence import (
    ExplorationEvidenceExport,
    TaskEvidenceCollector,
    TaskPageView,
)
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
    ["_TaskRuntimeContext", AuthenticationPlan, NavigationPolicy], _LoginRuntime
]
RunnerFactory = Callable[
    [
        "_TaskRuntimeContext",
        NavigationPolicy,
        ExplorationBudget,
        object,
        ExplorationCancellationToken,
    ],
    _TaskRunner,
]
CollectorFactory = Callable[["_TaskRuntimeContext"], object]
TerminalSummaryReader = Callable[[str], TaskSummary | None]
TerminalSummaryListReader = Callable[[], list[TaskSummary]]


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
    command: CreateExplorationTaskCommand
    policy: NavigationPolicy
    cancellation_token: ExplorationCancellationToken
    context: _TaskRuntimeContext
    evidence_collector: TaskEvidenceCollector
    runtime: _LoginRuntime | None = None
    startup_ready: Event = field(default_factory=Event)
    confirmation_requested: Event = field(default_factory=Event)
    confirmation_resolved: Event = field(default_factory=Event)
    runtime_closed: Event = field(default_factory=Event)
    confirmation_failed: bool = False
    confirmation_in_flight: bool = False
    on_terminal: Callable[[TaskSummary], None] | None = None
    terminal_notified: Event = field(default_factory=Event)


class _TaskRuntimeContext:
    """Private, controlled bridge to one hidden ExplorationTask identity."""

    def __init__(
        self,
        managed: ManagedTask,
        *,
        evidence_sink: ExplorationEvidenceSink | None = None,
    ) -> None:
        self._managed = managed
        self._evidence_sink = evidence_sink

    def start_collection(self) -> None:
        self._managed.start_collection()

    def pause_for_human(self, *, reason_code: str) -> None:
        self._managed.pause_for_human(reason_code=reason_code)

    def confirm_human_ready(self) -> None:
        self._managed.confirm_human_ready()

    def record_authentication_result(
        self,
        *,
        authenticated: bool,
        checkpoint_id: str | None,
    ) -> None:
        self._managed.record_authentication_result(
            authenticated=authenticated,
            checkpoint_id=checkpoint_id,
        )

    def complete(self) -> None:
        self._managed.complete()

    def create_session_collector(
        self,
        *,
        session: PlaywrightBrowserSession,
        limits: SnapshotLimits,
    ) -> SessionSnapshotCollectorAdapter:
        return self._managed._with_task(
            lambda task: SessionSnapshotCollectorAdapter(
                session=session,
                task=task,
                limits=limits,
            )
        )

    def create_human_login_session(
        self,
        *,
        plan: AuthenticationPlan,
        policy: NavigationPolicy,
        browser: PlaywrightBrowserSession,
        collector: SessionSnapshotCollectorAdapter,
    ) -> HumanLoginSession:
        return self._managed._with_task(
            lambda task: HumanLoginSession(
                task=task,
                plan=plan,
                policy=policy,
                browser=browser,
                collector=collector,
                register_terminal_cleanup=False,
            )
        )

    def create_runner(
        self,
        *,
        policy: NavigationPolicy,
        budget: ExplorationBudget,
        collector: object,
        cancellation_token: ExplorationCancellationToken,
    ) -> ExplorationRunner:
        if type(collector) is SnapshotCollectorAdapter:
            return ExplorationRunner(
                policy=policy,
                budget=budget,
                collector=cast(SnapshotCollectorPort, collector),
                cancellation_token=cancellation_token,
                evidence_sink=self._evidence_sink,
            )
        return self._managed._with_task(
            lambda task: ExplorationRunner(
                policy=policy,
                budget=budget,
                collector=cast(SnapshotCollectorPort, collector),
                interaction_candidate_extractor=extract_readonly_interaction_candidates,
                interaction_executor=cast(
                    SessionSnapshotCollectorAdapter,
                    collector,
                ).execute_readonly_interaction,
                interaction_snapshot_collector=cast(
                    SessionSnapshotCollectorAdapter,
                    collector,
                ).collect_current,
                task=task,
                cancellation_token=cancellation_token,
                evidence_sink=self._evidence_sink,
            )
        )


class ExplorationTaskService:
    """Create, observe, cancel, and resume in-memory exploration tasks."""

    def __init__(
        self,
        *,
        registry: ExplorationTaskRegistry,
        runtime_factory: RuntimeFactory,
        runner_factory: RunnerFactory,
        collector_factory: CollectorFactory | None = None,
        terminal_summary_reader: TerminalSummaryReader | None = None,
        terminal_summary_list_reader: TerminalSummaryListReader | None = None,
    ) -> None:
        self._registry = registry
        self._runtime_factory = runtime_factory
        self._runner_factory = runner_factory
        self._collector_factory = collector_factory or _empty_collector
        self._terminal_summary_reader = terminal_summary_reader
        self._terminal_summary_list_reader = terminal_summary_list_reader
        self._lock = RLock()
        self._executions: dict[str, _TaskExecution] = {}
        self._next_task_number = 1

    def create(
        self,
        command: CreateExplorationTaskCommand,
        *,
        evidence_sink: ExplorationEvidenceSink | None = None,
        on_terminal: Callable[[TaskSummary], None] | None = None,
    ) -> TaskSummary:
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
        task_evidence = TaskEvidenceCollector(downstream=evidence_sink)
        context = _TaskRuntimeContext(managed, evidence_sink=task_evidence)
        execution = _TaskExecution(
            command=command,
            policy=policy,
            cancellation_token=ExplorationCancellationToken(),
            context=context,
            evidence_collector=task_evidence,
            on_terminal=on_terminal,
        )
        with self._lock:
            self._executions[task.task_id] = execution
        task_id = task.task_id

        def release_runtime() -> None:
            self._release_runtime(task_id)

        managed.register_terminal_callback(release_runtime)

        if command.authentication_plan is not None:
            self._start_login_task(managed, execution)
            execution.startup_ready.wait(timeout=5)
            return managed.summary()

        try:
            managed.start_collection()
            managed.set_phase("collecting")
            self._start_runner(managed, execution, self._collector_factory(context))
        except Exception:
            self._fail_collecting_task(managed)
        return managed.summary()

    def get(self, task_id: str) -> TaskSummary | None:
        """Read a live task first, then one persisted terminal safe projection."""
        managed = self._registry.get(task_id)
        if managed is not None:
            return managed.summary()
        reader = self._terminal_summary_reader
        return reader(task_id) if reader is not None else None

    def list_summaries(self) -> list[TaskSummary]:
        """List live tasks plus persisted terminal summaries missing from this process."""
        summaries = {summary.task_id: summary for summary in self._registry.list_summaries()}
        reader = self._terminal_summary_list_reader
        if reader is not None:
            for summary in reader():
                summaries.setdefault(summary.task_id, summary)
        return [summaries[task_id] for task_id in sorted(summaries)]

    def knowledge_source(self, task_id: str) -> TaskKnowledgeSource | None:
        """Project one terminal task into bounded, already-redacted evidence."""
        summary = self.get(task_id)
        execution = self._execution_for(task_id)
        if summary is None or execution is None or str(summary.state) not in _TERMINAL_STATES:
            return None
        evidence_export = execution.evidence_collector.export(
            task_id=summary.task_id,
            state=summary.state,
            result=summary.result,
        )
        pages = [
            page
            for page_view in execution.evidence_collector.pages()
            if (page := execution.evidence_collector.page_detail(page_view.page_id)) is not None
        ]
        return TaskKnowledgeSource(
            source_id=summary.task_id,
            state=cast(
                Literal["completed", "partial", "failed", "cancelled"],
                str(summary.state),
            ),
            pages=pages,
            reason_codes=list(evidence_export.reason_codes),
            workflow=execution.evidence_collector.workflow(
                task_id=summary.task_id,
                state=summary.state,
            ),
        )

    def events(self, task_id: str) -> list[TaskEventView] | None:
        """Return only allowlisted audit event fields."""
        summary = self.get(task_id)
        return list(summary.events) if summary is not None else None

    def confirm_login(self, task_id: str) -> TaskSummary:
        """Signal the owning login thread to verify explicit human completion."""
        managed = self._require_managed(task_id)
        if managed.summary().state != "paused_for_human":
            raise TaskServiceError("Task cannot confirm login.")
        execution = self._require_execution(task_id)
        with self._lock:
            if execution.runtime is None or execution.confirmation_in_flight:
                raise TaskServiceError("Task cannot confirm login.")
            execution.confirmation_failed = False
            execution.confirmation_in_flight = True
            execution.confirmation_resolved.clear()
            execution.confirmation_requested.set()
        if not execution.confirmation_resolved.wait(timeout=5):
            raise TaskServiceError("Task cannot confirm login.")
        with self._lock:
            confirmation_failed = execution.confirmation_failed
        if confirmation_failed:
            raise TaskServiceError("Task cannot confirm login.")
        return managed.summary()

    def cancel(self, task_id: str) -> TaskSummary:
        """Cancel once and trigger registered terminal cleanup; repeated cancel is safe."""
        managed = self._require_managed(task_id)
        current_summary = managed.summary()
        if current_summary.state in _TERMINAL_STATES:
            if current_summary.state == "cancelled":
                return current_summary
            raise TaskServiceError("Task cannot be cancelled.")
        execution = self._execution_for(task_id)
        runtime = execution.runtime if execution is not None else None
        if execution is not None:
            execution.cancellation_token.cancel()
            execution.confirmation_requested.set()
        try:
            managed.cancel(reason_code="user_cancelled")
        except ExplorationTaskError:
            raise TaskServiceError("Task cannot be cancelled.") from None
        managed.set_phase("cancelled")
        if execution is not None and runtime is not None:
            execution.runtime_closed.wait(timeout=5)
        return managed.summary()

    def result(self, task_id: str) -> TaskResultSummary | None:
        """Return only the stored redacted result summary."""
        summary = self.get(task_id)
        return summary.result if summary is not None else None

    def pages(self, task_id: str) -> list[TaskPageView] | None:
        """Return process-local page indexes without Snapshot or runtime handles."""
        execution = self._execution_for(task_id)
        return execution.evidence_collector.pages() if execution is not None else None

    def page_detail(self, task_id: str, page_id: str) -> PageEvidence | None:
        """Return one already-redacted page evidence record."""
        execution = self._execution_for(task_id)
        return execution.evidence_collector.page_detail(page_id) if execution is not None else None

    def export(self, task_id: str) -> ExplorationEvidenceExport | None:
        """Build a schema-valid, process-local export from bounded projections."""
        summary = self.get(task_id)
        execution = self._execution_for(task_id)
        if summary is None or execution is None:
            return None
        return execution.evidence_collector.export(
            task_id=summary.task_id,
            state=summary.state,
            result=summary.result,
        )

    def workflow(self, task_id: str) -> TaskWorkflowExport | None:
        """Return a terminal task's process-local readonly workflow projection."""
        summary = self.get(task_id)
        execution = self._execution_for(task_id)
        if summary is None or execution is None or str(summary.state) not in _TERMINAL_STATES:
            return None
        return execution.evidence_collector.workflow(
            task_id=summary.task_id,
            state=summary.state,
        )

    def _start_login_task(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
    ) -> None:
        thread = Thread(
            target=self._run_login_task,
            args=(managed, execution),
            daemon=True,
            name=f"ai-ui-explorer-login-{managed.task_id}",
        )
        managed.attach_thread(thread)
        thread.start()

    def _run_login_task(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
    ) -> None:
        runtime: _LoginRuntime | None = None
        try:
            assert execution.command.authentication_plan is not None
            runtime = self._runtime_factory(
                execution.context,
                execution.command.authentication_plan,
                execution.policy,
            )
            execution.runtime = runtime
            managed.attach_runtime(runtime)
            runtime.start()
            self._sync_phase(managed)
        except Exception:
            self._fail_login_start(managed)
            if runtime is not None:
                try:
                    runtime.close()
                except Exception:
                    pass
            execution.runtime_closed.set()
            self._notify_terminal(execution, managed.summary())
            return
        finally:
            execution.startup_ready.set()

        try:
            while (
                not execution.cancellation_token.is_cancelled
                and managed.summary().state == "paused_for_human"
            ):
                execution.confirmation_requested.wait()
                execution.confirmation_requested.clear()
                if execution.cancellation_token.is_cancelled:
                    break
                self._verify_login_in_owner_thread(managed, execution, runtime)
        finally:
            if runtime is not None and managed.summary().state in _TERMINAL_STATES:
                try:
                    runtime.close()
                except Exception:
                    pass
            execution.runtime_closed.set()
            self._notify_terminal(execution, managed.summary())

    def _verify_login_in_owner_thread(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
        runtime: _LoginRuntime,
    ) -> None:
        failed = False
        try:
            verification = runtime.confirm_and_verify()
            if not verification.authenticated:
                self._sync_phase(managed)
            elif not managed.has_verified_authentication():
                self._reject_unverified_confirmation(managed)
                failed = True
            else:
                managed.set_phase("collecting")
                runner = self._runner_factory(
                    execution.context,
                    execution.policy,
                    execution.command.budget,
                    runtime.collector_port(),
                    execution.cancellation_token,
                )
                self._resolve_login_confirmation(execution, failed=False)
                self._run_runner(managed, execution, runner)
                return
        except Exception:
            if managed.summary().state == "collecting":
                self._fail_collecting_task(managed)
            else:
                self._reject_unverified_confirmation(managed)
            failed = True
        self._resolve_login_confirmation(execution, failed=failed)

    def _resolve_login_confirmation(
        self,
        execution: _TaskExecution,
        *,
        failed: bool,
    ) -> None:
        with self._lock:
            execution.confirmation_failed = failed
            execution.confirmation_in_flight = False
            execution.confirmation_resolved.set()

    def _start_runner(
        self,
        managed: ManagedTask,
        execution: _TaskExecution,
        collector: object,
    ) -> None:
        runner = self._runner_factory(
            execution.context,
            execution.policy,
            execution.command.budget,
            collector,
            execution.cancellation_token,
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
            self._record_run_result(managed, result)
            self._complete_if_runner_did_not_finalize(managed, result)
        except Exception:
            self._fail_collecting_task(managed)
        finally:
            self._sync_phase(managed)
            if managed.summary().state in _TERMINAL_STATES:
                self._release_runtime(managed.task_id)
                if execution.command.authentication_plan is None:
                    self._notify_terminal(execution, managed.summary())

    def _record_run_result(self, managed: ManagedTask, result: object) -> None:
        visits = getattr(result, "visits", None)
        visit_count = (
            len(visits)
            if isinstance(visits, Sequence)
            else getattr(
                result,
                "visit_count",
                0,
            )
        )
        if not isinstance(visit_count, int) or visit_count < 0:
            visit_count = 0
        element_count = _count_visit_metric(visits, "element_count")
        link_count = _count_visit_metric(visits, "link_count")
        managed.set_result(
            TaskResultSummary(
                page_count=visit_count,
                element_count=element_count,
                link_count=link_count,
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
        state = managed.summary().state
        if state == "created":
            managed.start_collection()
            state = managed.summary().state
        if state == "collecting":
            managed.fail(reason_code="login_runtime_error")
        elif state not in _TERMINAL_STATES:
            managed.cancel(reason_code="login_runtime_error")
        self._sync_phase(managed)

    def _reject_unverified_confirmation(self, managed: ManagedTask) -> None:
        if managed.summary().state == "verifying_authentication":
            managed.record_authentication_result(
                authenticated=False,
                checkpoint_id=None,
            )
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
        execution = self._execution_for(task_id)
        if execution is None:
            raise TaskServiceError("Task cannot be resumed.")
        return execution

    def _execution_for(self, task_id: str) -> _TaskExecution | None:
        with self._lock:
            return self._executions.get(task_id)

    def _release_runtime(self, task_id: str) -> None:
        self._registry.remove_runtime(task_id)
        with self._lock:
            execution = self._executions.get(task_id)
            if execution is not None:
                execution.runtime = None

    def _notify_terminal(
        self,
        execution: _TaskExecution,
        summary: TaskSummary,
    ) -> None:
        if execution.terminal_notified.is_set():
            return
        execution.terminal_notified.set()
        callback = execution.on_terminal
        if callback is None:
            return
        try:
            callback(summary)
        except Exception:
            pass


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


def _count_visit_metric(visits: object, attribute: str) -> int:
    """Add bounded scalar visit metadata without retaining snapshot content."""
    if not isinstance(visits, Sequence):
        return 0
    total = 0
    for visit in visits:
        value = getattr(visit, attribute, 0)
        if isinstance(value, int) and value >= 0:
            total += value
    return total


def _empty_collector(_context: _TaskRuntimeContext) -> object:
    """Provide no browser state until a production collector is wired by the API."""
    return object()
