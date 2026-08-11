"""Safe public views and process-local task handles for exploration tasks."""

import re
from collections.abc import Callable
from datetime import datetime
from threading import RLock

from pydantic import Field, field_validator

from ai_ui_explorer.exploration.task import AuditEvent, ExplorationTask, ExplorationTaskState
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel

_SAFE_PHASES = frozenset(
    {
        "created",
        "collecting",
        "awaiting_human",
        "verifying_authentication",
        "completed",
        "partial",
        "failed",
        "cancelled",
    }
)
_SAFE_EVENT_TYPES = frozenset(
    {
        "task_created",
        "collection_started",
        "paused_for_human",
        "human_confirmed",
        "authentication_verified",
        "collection_resumed",
        "task_completed",
        "task_partial",
        "task_failed",
        "task_cancelled",
        "authentication_rejected",
        "terminal_callback_failed",
        "event_withheld",
    }
)
_SAFE_REASON_CODES = frozenset(
    {
        "authentication_required",
        "collector_failure",
        "runner_failure",
        "user_cancelled",
        "cleanup_failure",
        "login_runtime_error",
        "reason_withheld",
    }
)
_SAFE_CHECKPOINT_ID = "checkpoint_available"
_SAFE_TASK_ID = re.compile(r"^task-[0-9]{1,20}$")
_SAFE_SOURCE_SUMMARY = re.compile(
    r"^redacted source(?:: origin-[0-9]{1,20})?$"
)


def _require_safe_task_id(value: str) -> str:
    if _SAFE_TASK_ID.fullmatch(value) is None:
        raise ValueError("task ID must use the public identifier format")
    return value


def _require_safe_phase(value: str) -> str:
    if value not in _SAFE_PHASES:
        raise ValueError("task phase is not allowed in the public view")
    return value


class TaskEventView(DeepFrozenModel):
    """A serializable, allowlisted audit event for task clients."""

    event_type: str = Field(min_length=1)
    reason_code: str | None = None
    checkpoint_id: str | None = None
    occurred_at: datetime

    @field_validator("event_type")
    @classmethod
    def require_safe_event_type(cls, value: str) -> str:
        if value not in _SAFE_EVENT_TYPES:
            raise ValueError("event type is not allowed in the public view")
        return value

    @field_validator("reason_code")
    @classmethod
    def require_safe_reason_code(cls, value: str | None) -> str | None:
        if value is not None and value not in _SAFE_REASON_CODES:
            raise ValueError("reason code is not allowed in the public view")
        return value

    @field_validator("checkpoint_id")
    @classmethod
    def require_safe_checkpoint_id(cls, value: str | None) -> str | None:
        if value is not None and value != _SAFE_CHECKPOINT_ID:
            raise ValueError("checkpoint ID is not allowed in the public view")
        return value


class TaskResultSummary(DeepFrozenModel):
    """Counts and a redacted source description, without snapshot payloads."""

    page_count: int = Field(ge=0)
    element_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    source_summary: str = Field(min_length=1)

    @field_validator("source_summary")
    @classmethod
    def reject_sensitive_source_text(cls, value: str) -> str:
        if _SAFE_SOURCE_SUMMARY.fullmatch(value) is None:
            raise ValueError("source summary must use the redacted public format")
        return value


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

    @field_validator("task_id")
    @classmethod
    def require_safe_task_id(cls, value: str) -> str:
        return _require_safe_task_id(value)

    @field_validator("phase")
    @classmethod
    def require_safe_phase(cls, value: str) -> str:
        return _require_safe_phase(value)


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
        _require_safe_task_id(task.task_id)
        _require_safe_phase(phase)
        if not task.audit_events:
            raise ValueError("managed tasks require at least one audit event")
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

    def start_collection(self) -> None:
        """Start collection through the handle's synchronization boundary."""
        with self._lock:
            self._task.start_collection()

    def pause_for_human(self, *, reason_code: str) -> None:
        """Pause collection through the handle's synchronization boundary."""
        with self._lock:
            self._task.pause_for_human(reason_code=reason_code)

    def confirm_human_ready(self) -> None:
        """Confirm human readiness through the handle's synchronization boundary."""
        with self._lock:
            self._task.confirm_human_ready()

    def record_authentication_result(
        self,
        *,
        authenticated: bool,
        checkpoint_id: str | None,
    ) -> None:
        """Record an authentication result through the synchronization boundary."""
        with self._lock:
            self._task.record_authentication_result(
                authenticated=authenticated,
                checkpoint_id=checkpoint_id,
            )

    def complete(self) -> None:
        """Complete the task through the handle's synchronization boundary."""
        with self._lock:
            self._task.complete()

    def mark_partial(self, *, reason_code: str) -> None:
        """Mark a task partial through the handle's synchronization boundary."""
        with self._lock:
            self._task.mark_partial(reason_code=reason_code)

    def fail(self, *, reason_code: str) -> None:
        """Fail the task through the handle's synchronization boundary."""
        with self._lock:
            self._task.fail(reason_code=reason_code)

    def cancel(self, *, reason_code: str) -> None:
        """Cancel the task through the handle's synchronization boundary."""
        with self._lock:
            self._task.cancel(reason_code=reason_code)

    def register_terminal_callback(self, callback: Callable[[], None]) -> None:
        """Register process-local terminal cleanup through the same boundary."""
        with self._lock:
            self._task.register_terminal_callback(callback)

    def set_phase(self, phase: str) -> None:
        """Update the public lifecycle phase without exposing runtime handles."""
        _require_safe_phase(phase)
        with self._lock:
            self._phase = phase

    def set_result(self, result: TaskResultSummary) -> None:
        """Replace the safe result summary through the synchronization boundary."""
        with self._lock:
            self._result = result

    def attach_runtime(self, runtime: object) -> None:
        """Retain one process-local runtime without making it serializable."""
        with self._lock:
            self._runtime = runtime

    def attach_thread(self, thread: object) -> None:
        """Retain one process-local worker handle without making it serializable."""
        with self._lock:
            self._thread = thread

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
    return TaskEventView(
        event_type=(
            event.event_type
            if event.event_type in _SAFE_EVENT_TYPES
            else "event_withheld"
        ),
        reason_code=(
            event.reason_code
            if event.reason_code in _SAFE_REASON_CODES
            else "reason_withheld"
            if event.reason_code is not None
            else None
        ),
        checkpoint_id=(
            _SAFE_CHECKPOINT_ID if event.checkpoint_id is not None else None
        ),
        occurred_at=event.occurred_at,
    )
