"""State machine for controlled exploration tasks."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, PrivateAttr

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel


class ExplorationTaskError(RuntimeError):
    """Safe state-machine failure surface."""


class ExplorationTaskState(StrEnum):
    CREATED = "created"
    COLLECTING = "collecting"
    PAUSED_FOR_HUMAN = "paused_for_human"
    VERIFYING_AUTHENTICATION = "verifying_authentication"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATES = frozenset(
    {
        ExplorationTaskState.COMPLETED,
        ExplorationTaskState.PARTIAL,
        ExplorationTaskState.FAILED,
        ExplorationTaskState.CANCELLED,
    }
)


class AuditEvent(DeepFrozenModel):
    event_type: str = Field(min_length=1)
    reason_code: str | None = None
    checkpoint_id: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExplorationTask(DeepFrozenModel):
    task_id: str = Field(min_length=1)
    state: ExplorationTaskState
    audit_events: list[AuditEvent]
    checkpoint_id: str | None = None
    _terminal_callbacks: list[Callable[[], None]] = PrivateAttr(
        default_factory=list
    )

    @classmethod
    def create(cls, *, task_id: str) -> "ExplorationTask":
        return cls(
            task_id=task_id,
            state=ExplorationTaskState.CREATED,
            audit_events=[AuditEvent(event_type="task_created")],
        )

    def start_collection(self) -> None:
        self._require_not_terminal()
        self._require_state(ExplorationTaskState.CREATED)
        self._set_state(ExplorationTaskState.COLLECTING)
        self._append_event("collection_started")

    def register_terminal_callback(self, callback: Callable[[], None]) -> None:
        """Run process-local cleanup synchronously when the task becomes terminal."""
        if self.state in _TERMINAL_STATES:
            callback()
            return
        self._terminal_callbacks.append(callback)

    def pause_for_human(self, *, reason_code: str) -> None:
        self._require_not_terminal()
        self._require_state(ExplorationTaskState.COLLECTING)
        self._set_state(ExplorationTaskState.PAUSED_FOR_HUMAN)
        self._append_event("paused_for_human", reason_code=reason_code)

    def confirm_human_ready(self) -> None:
        self._require_not_terminal()
        self._require_state(ExplorationTaskState.PAUSED_FOR_HUMAN)
        self._set_state(ExplorationTaskState.VERIFYING_AUTHENTICATION)
        self._append_event("human_confirmed")

    def record_authentication_result(
        self,
        *,
        authenticated: bool,
        checkpoint_id: str | None,
    ) -> None:
        self._require_not_terminal()
        self._require_state(ExplorationTaskState.VERIFYING_AUTHENTICATION)
        if not authenticated:
            self._set_state(ExplorationTaskState.PAUSED_FOR_HUMAN)
            self._append_event("authentication_rejected")
            return
        if checkpoint_id is None or not checkpoint_id.strip():
            raise ExplorationTaskError("checkpoint is required before resume")
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        self._append_event(
            "authentication_verified",
            checkpoint_id=checkpoint_id,
        )
        self._set_state(ExplorationTaskState.COLLECTING)
        self._append_event("collection_resumed")

    def complete(self) -> None:
        self._require_not_terminal()
        self._require_state(ExplorationTaskState.COLLECTING)
        self._set_state(ExplorationTaskState.COMPLETED)
        self._append_event("task_completed")
        self._notify_terminal_callbacks()

    def mark_partial(self, *, reason_code: str) -> None:
        self._require_not_terminal()
        self._require_state(ExplorationTaskState.COLLECTING)
        self._set_state(ExplorationTaskState.PARTIAL)
        self._append_event("task_partial", reason_code=reason_code)
        self._notify_terminal_callbacks()

    def cancel(self, *, reason_code: str) -> None:
        self._require_not_terminal()
        self._set_state(ExplorationTaskState.CANCELLED)
        self._append_event("task_cancelled", reason_code=reason_code)
        self._notify_terminal_callbacks()

    def _require_not_terminal(self) -> None:
        if self.state in _TERMINAL_STATES:
            raise ExplorationTaskError("terminal task cannot transition")

    def _require_state(self, expected: ExplorationTaskState) -> None:
        if self.state != expected:
            raise ExplorationTaskError("invalid transition")

    def _set_state(self, state: ExplorationTaskState) -> None:
        object.__setattr__(self, "state", state)

    def _append_event(
        self,
        event_type: str,
        *,
        reason_code: str | None = None,
        checkpoint_id: str | None = None,
    ) -> None:
        object.__setattr__(
            self,
            "audit_events",
            [
                *self.audit_events,
                AuditEvent(
                    event_type=event_type,
                    reason_code=reason_code,
                    checkpoint_id=checkpoint_id,
                ),
            ],
        )

    def _notify_terminal_callbacks(self) -> None:
        callbacks = tuple(self._terminal_callbacks)
        self._terminal_callbacks.clear()
        for callback in callbacks:
            callback()
