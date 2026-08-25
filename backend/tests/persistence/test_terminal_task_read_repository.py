from datetime import UTC, datetime

from ai_ui_explorer.persistence.models import ExplorationTaskRecord
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def test_repository_returns_valid_terminal_task_summary() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(_record(state="completed"))  # type: ignore[arg-type]
    )

    summary = repository.get_terminal_task_summary("task-1")

    assert summary is not None
    assert summary.task_id == "task-1"
    assert summary.state == "completed"


def test_repository_hides_nonterminal_task_record() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(_record(state="collecting"))  # type: ignore[arg-type]
    )

    assert repository.get_terminal_task_summary("task-1") is None


def test_repository_returns_process_restart_interruption_as_safe_failed_summary() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(_interrupted_record())  # type: ignore[arg-type]
    )

    summary = repository.get_terminal_task_summary("task-1")

    assert summary is not None
    assert summary.state == "failed"
    assert summary.phase == "interrupted"
    assert summary.events[-1].event_type == "process_restarted"
    assert summary.events[-1].reason_code == "process_restarted"


class _FakeSession:
    def __init__(self, record: ExplorationTaskRecord) -> None:
        self._record = record
        self.closed = False

    def get(self, _model: object, task_id: str) -> ExplorationTaskRecord | None:
        return self._record if task_id == self._record.task_id else None

    def commit(self) -> None:
        raise AssertionError("read operation must not commit")

    def rollback(self) -> None:
        raise AssertionError("read operation must not roll back")

    def close(self) -> None:
        self.closed = True


def _record(*, state: str) -> ExplorationTaskRecord:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return ExplorationTaskRecord(
        task_id="task-1",
        state=state,
        phase=state,
        created_at=timestamp,
        updated_at=timestamp,
        redaction_count=0,
        result_json={
            "page_count": 0,
            "element_count": 0,
            "link_count": 0,
            "source_summary": "redacted source",
        },
        events_json=[
            {
                "event_type": "task_completed",
                "reason_code": None,
                "checkpoint_id": None,
                "occurred_at": "2026-08-19T00:00:00Z",
            }
        ],
        schema_version="1.0",
    )


def _interrupted_record() -> ExplorationTaskRecord:
    record = _record(state="failed")
    record.phase = "interrupted"
    record.events_json = [
        {
            "event_type": "process_restarted",
            "reason_code": "process_restarted",
            "checkpoint_id": None,
            "occurred_at": "2026-08-19T00:00:00Z",
        }
    ]
    return record
