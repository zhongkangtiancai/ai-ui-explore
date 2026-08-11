"""Tests for the in-memory exploration task registry."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from ai_ui_explorer.exploration.task import AuditEvent, ExplorationTask, ExplorationTaskState
from ai_ui_explorer.task_management.models import ManagedTask, TaskResultSummary
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry


class FakeRuntime:
    """A deliberately sensitive stand-in for an in-process runtime."""

    def __repr__(self) -> str:
        return (
            "FakeRuntime(cookie=runtime-cookie, token=runtime-token, "
            "page=sensitive-page, context=sensitive-context)"
        )


class FakeThread:
    """A deliberately sensitive stand-in for a background thread handle."""

    def __repr__(self) -> str:
        return "FakeThread(thread=sensitive-thread, password=thread-password)"


def make_managed_task(task_id: str = "task-1") -> ManagedTask:
    managed_task = ManagedTask(
        task=ExplorationTask.create(task_id=task_id),
        phase="awaiting_human",
        result=TaskResultSummary(
            page_count=1,
            element_count=4,
            link_count=2,
            source_summary="redacted source: origin-1",
        ),
        redaction_count=3,
        runtime=FakeRuntime(),
        thread=FakeThread(),
    )
    managed_task.start_collection()
    managed_task.pause_for_human(reason_code="authentication_required")
    return managed_task


def test_registry_exposes_only_safe_task_view() -> None:
    registry = ExplorationTaskRegistry()
    task = registry.create(make_managed_task())

    view = registry.get(task.task_id).summary()  # type: ignore[union-attr]

    assert view.task_id == task.task_id
    serialized = view.model_dump_json().lower()
    representation = repr(view).lower()
    for forbidden_value in (
        "cookie",
        "token",
        "password",
        "storage_state",
        "sensitive-page",
        "sensitive-context",
        "sensitive-thread",
        "fakeruntime",
        "fakethread",
    ):
        assert forbidden_value not in serialized
        assert forbidden_value not in representation


def test_registry_returns_none_for_unknown_task() -> None:
    assert ExplorationTaskRegistry().get("missing") is None


@pytest.mark.parametrize(
    "source_summary",
    [
        "cookie=raw-secret",
        "密码=raw-secret",
        "验证码=raw-secret",
        "令牌=raw-secret",
        "redacted source: cookie.example",
        "redacted source: token.example",
        "redacted source: password.example",
        "redacted source: context.example",
        "redacted source: runtime.example",
        "redacted source: thread.example",
    ],
)
def test_result_summary_rejects_sensitive_source_text(source_summary: str) -> None:
    with pytest.raises(ValidationError):
        TaskResultSummary(
            page_count=1,
            element_count=1,
            link_count=0,
            source_summary=source_summary,
        )


@pytest.mark.parametrize("task_id", ["cookie", "token", "password", "context", "runtime", "thread"])
def test_managed_task_rejects_sensitive_task_id(task_id: str) -> None:
    with pytest.raises(ValueError):
        ManagedTask(
            task=ExplorationTask.create(task_id=task_id),
            phase="created",
            result=TaskResultSummary(
                page_count=0,
                element_count=0,
                link_count=0,
                source_summary="redacted source",
            ),
            redaction_count=0,
        )


def test_managed_task_rejects_sensitive_public_phase() -> None:
    with pytest.raises(ValueError):
        ManagedTask(
            task=ExplorationTask.create(task_id="task-1"),
            phase="runtime_pending",
            result=TaskResultSummary(
                page_count=0,
                element_count=0,
                link_count=0,
                source_summary="redacted source",
            ),
            redaction_count=0,
        )


@pytest.mark.parametrize("phase", ["Context", "等待密码", "等待验证码", "等待令牌"])
def test_managed_task_rejects_non_allowlisted_public_phase(phase: str) -> None:
    with pytest.raises(ValueError):
        ManagedTask(
            task=ExplorationTask.create(task_id="task-1"),
            phase=phase,
            result=TaskResultSummary(
                page_count=0,
                element_count=0,
                link_count=0,
                source_summary="redacted source",
            ),
            redaction_count=0,
        )


def test_managed_task_exposes_controlled_transitions_without_task_object() -> None:
    managed_task = ManagedTask(
        task=ExplorationTask.create(task_id="task-1"),
        phase="created",
        result=TaskResultSummary(
            page_count=0,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
        redaction_count=0,
    )

    managed_task.start_collection()

    assert not hasattr(managed_task, "task")
    assert managed_task.summary().state == ExplorationTaskState.COLLECTING


def test_managed_task_withholds_unallowlisted_audit_details() -> None:
    managed_task = ManagedTask(
        task=ExplorationTask(
            task_id="task-1",
            state=ExplorationTaskState.PAUSED_FOR_HUMAN,
            audit_events=[
                AuditEvent(event_type="task_created"),
                AuditEvent(
                    event_type="paused_for_human",
                    reason_code="密码=raw-secret",
                    checkpoint_id="Context(raw-secret)",
                ),
            ],
        ),
        phase="awaiting_human",
        result=TaskResultSummary(
            page_count=0,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
        redaction_count=0,
    )

    view = managed_task.summary()

    assert view.events[-1].reason_code == "reason_withheld"
    assert view.events[-1].checkpoint_id == "checkpoint_available"
    serialized = view.model_dump_json().lower()
    for forbidden_value in ("密码", "验证码", "令牌", "cookie", "context"):
        assert forbidden_value not in serialized


def test_managed_task_rejects_empty_audit_events() -> None:
    with pytest.raises(ValueError, match="audit"):
        ManagedTask(
            task=ExplorationTask(
                task_id="task-1",
                state=ExplorationTaskState.CREATED,
                audit_events=[],
            ),
            phase="created",
            result=TaskResultSummary(
                page_count=0,
                element_count=0,
                link_count=0,
                source_summary="redacted source",
            ),
            redaction_count=0,
        )


def test_registry_handles_concurrent_create_and_get() -> None:
    registry = ExplorationTaskRegistry()
    task_ids = [f"task-{index}" for index in range(24)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(
            executor.map(
                lambda task_id: registry.create(make_managed_task(task_id)),
                task_ids,
            )
        )
        found = list(executor.map(lambda task: registry.get(task.task_id), created))

    assert [task.task_id for task in found if task is not None] == task_ids


def test_remove_runtime_preserves_public_summary() -> None:
    registry = ExplorationTaskRegistry()
    task = registry.create(make_managed_task())
    expected = task.summary()

    registry.remove_runtime(task.task_id)

    stored_task = registry.get(task.task_id)
    assert stored_task is not None
    assert stored_task.summary() == expected
    assert "runtime" not in repr(stored_task).lower()
    assert "thread" not in repr(stored_task).lower()
