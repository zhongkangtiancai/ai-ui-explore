"""Safe public views and process-local task handles for exploration tasks."""

from datetime import datetime
from threading import RLock

from pydantic import Field, field_validator

from ai_ui_explorer.exploration.task import AuditEvent, ExplorationTask, ExplorationTaskState
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel

_SENSITIVE_MARKERS = (
    "cookie",
    "token",
    "password",
    "verification code",
    "storage_state",
    "storage state",
    "screenshot",
    "network body",
    "runtime",
    "thread",
)


def _contains_sensitive_marker(value: str) -> bool:
    return any(marker in value.lower() for marker in _SENSITIVE_MARKERS)


def _require_safe_text(value: str) -> str:
    if _contains_sensitive_marker(value):
        raise ValueError("task views cannot include sensitive runtime text")
    return value


class TaskEventView(DeepFrozenModel):
    """A serializable, allowlisted audit event for task clients."""

    event_type: str = Field(min_length=1)
    reason_code: str | None = None
    checkpoint_id: str | None = None
    occurred_at: datetime

    @field_validator("event_type", "reason_code", "checkpoint_id")
    @classmethod
    def reject_sensitive_text(cls, value: str | None) -> str | None:
        return None if value is None else _require_safe_text(value)


class TaskResultSummary(DeepFrozenModel):
    """Counts and a redacted source description, without snapshot payloads."""

    page_count: int = Field(ge=0)
    element_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    source_summary: str = Field(min_length=1)

    @field_validator("source_summary")
    @classmethod
    def reject_sensitive_source_text(cls, value: str) -> str:
        return _require_safe_text(value)


class TaskSummary(DeepFrozenModel):
    """The complete serializable view of one managed exploration task."""

    task_id: str = Field(min_length=1)
    state: ExplorationTaskState
    phase: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    redaction_count: int = Field(ge=0)
    events: list[TaskEventView]
    result: TaskResultSummary

    @field_validator("task_id", "phase")
    @classmethod
    def reject_sensitive_text(cls, value: str) -> str:
        return _require_safe_text(value)


class ManagedTask:
    """One task's safe view plus private, in-memory-only runtime handles."""

    def __init__(
        self,
        *,
        task: ExplorationTask,
        phase: str,
        result: TaskResultSummary,
        redaction_count: int,
        runtime: object | None = None,
        thread: object | None = None,
    ) -> None:
        _require_safe_text(task.task_id)
        _require_safe_text(phase)
        if redaction_count < 0:
            raise ValueError("redaction count cannot be negative")
        self._lock = RLock()
        self._task = task
        self._phase = phase
        self._result = result
        self._redaction_count = redaction_count
        self._runtime = runtime
        self._thread = thread

    @property
    def task_id(self) -> str:
        with self._lock:
            return self._task.task_id

    @property
    def task(self) -> ExplorationTask:
        """Return the state-machine task for in-process orchestration only."""
        with self._lock:
            return self._task

    def summary(self) -> TaskSummary:
        """Return a locked, serializable view that excludes runtime handles."""
        with self._lock:
            events = [_event_view(event) for event in self._task.audit_events]
            created_at = events[0].occurred_at
            updated_at = events[-1].occurred_at
            return TaskSummary(
                task_id=self._task.task_id,
                state=self._task.state,
                phase=self._phase,
                created_at=created_at,
                updated_at=updated_at,
                redaction_count=self._redaction_count,
                events=events,
                result=self._result,
            )

    def remove_runtime(self) -> None:
        """Drop only non-serializable handles while retaining the safe summary."""
        with self._lock:
            self._runtime = None
            self._thread = None

    def __repr__(self) -> str:
        with self._lock:
            return (
                "ManagedTask("
                f"task_id={self._task.task_id!r}, "
                f"state={self._task.state.value!r}, "
                f"phase={self._phase!r})"
            )


def _event_view(event: AuditEvent) -> TaskEventView:
    if _contains_sensitive_marker(event.event_type):
        return TaskEventView(
            event_type="sensitive_event_withheld",
            occurred_at=event.occurred_at,
        )
    return TaskEventView(
        event_type=event.event_type,
        reason_code=(
            None
            if event.reason_code is None or _contains_sensitive_marker(event.reason_code)
            else event.reason_code
        ),
        checkpoint_id=(
            None
            if event.checkpoint_id is None
            or _contains_sensitive_marker(event.checkpoint_id)
            else event.checkpoint_id
        ),
        occurred_at=event.occurred_at,
    )
