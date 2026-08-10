"""Sprint 4 task state machine tests."""

import pytest

from ai_ui_explorer.exploration.task import (
    ExplorationTask,
    ExplorationTaskError,
    ExplorationTaskState,
)


def test_task_state_machine_records_valid_lifecycle() -> None:
    task = ExplorationTask.create(task_id="task-1")

    task.start_collection()
    task.pause_for_human(reason_code="authentication_required")
    task.confirm_human_ready()
    task.record_authentication_result(authenticated=True, checkpoint_id="checkpoint-1")
    task.complete()

    assert task.state == ExplorationTaskState.COMPLETED
    assert [event.event_type for event in task.audit_events] == [
        "task_created",
        "collection_started",
        "paused_for_human",
        "human_confirmed",
        "authentication_verified",
        "collection_resumed",
        "task_completed",
    ]


def test_partial_transition_records_reason_and_notifies_callback() -> None:
    task = ExplorationTask.create(task_id="task-1")
    observed_states: list[ExplorationTaskState] = []
    task.register_terminal_callback(lambda: observed_states.append(task.state))
    task.start_collection()

    task.mark_partial(reason_code="collector_failure")

    assert task.state == ExplorationTaskState.PARTIAL
    assert task.audit_events[-1].event_type == "task_partial"
    assert task.audit_events[-1].reason_code == "collector_failure"
    assert observed_states == [ExplorationTaskState.PARTIAL]


def test_task_cannot_verify_without_human_confirmation() -> None:
    task = ExplorationTask.create(task_id="task-1")
    task.start_collection()
    task.pause_for_human(reason_code="authentication_required")

    with pytest.raises(ExplorationTaskError, match="invalid transition"):
        task.record_authentication_result(
            authenticated=True,
            checkpoint_id="checkpoint-1",
        )


def test_task_cannot_resume_without_checkpoint() -> None:
    task = ExplorationTask.create(task_id="task-1")
    task.start_collection()
    task.pause_for_human(reason_code="authentication_required")
    task.confirm_human_ready()

    with pytest.raises(ExplorationTaskError, match="checkpoint"):
        task.record_authentication_result(authenticated=True, checkpoint_id=None)


def test_failed_authentication_returns_to_pause() -> None:
    task = ExplorationTask.create(task_id="task-1")
    task.start_collection()
    task.pause_for_human(reason_code="authentication_required")
    task.confirm_human_ready()

    task.record_authentication_result(authenticated=False, checkpoint_id=None)

    assert task.state == ExplorationTaskState.PAUSED_FOR_HUMAN
    assert task.audit_events[-1].event_type == "authentication_rejected"


def test_terminal_task_rejects_new_collection() -> None:
    task = ExplorationTask.create(task_id="task-1")
    task.cancel(reason_code="user_cancelled")

    with pytest.raises(ExplorationTaskError, match="terminal"):
        task.start_collection()


@pytest.mark.parametrize(
    "terminal_state",
    [ExplorationTaskState.COMPLETED, ExplorationTaskState.CANCELLED],
)
def test_terminal_transition_notifies_registered_callback_synchronously(
    terminal_state: ExplorationTaskState,
) -> None:
    task = ExplorationTask.create(task_id="task-1")
    observed_states: list[ExplorationTaskState] = []
    task.register_terminal_callback(lambda: observed_states.append(task.state))
    task.start_collection()

    if terminal_state == ExplorationTaskState.COMPLETED:
        task.complete()
    else:
        task.cancel(reason_code="user_cancelled")

    assert observed_states == [terminal_state]


def test_registering_terminal_callback_after_terminal_state_notifies_immediately() -> None:
    task = ExplorationTask.create(task_id="task-1")
    task.cancel(reason_code="user_cancelled")
    notifications = 0

    def record_notification() -> None:
        nonlocal notifications
        notifications += 1

    task.register_terminal_callback(record_notification)

    assert notifications == 1
