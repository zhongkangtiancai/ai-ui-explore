from datetime import UTC, datetime

from ai_ui_explorer.persistence.models import ExplorationTaskRecord
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def test_repository_interrupts_only_nonterminal_tasks_with_minimal_safe_event() -> None:
    collecting = _record(task_id="task-1", state="collecting", phase="collecting")
    completed = _record(task_id="task-2", state="completed", phase="completed")
    session = _FakeSession([collecting, completed])
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    timestamp = datetime(2026, 8, 18, tzinfo=UTC)

    interrupted_ids = repository.interrupt_nonterminal_tasks(occurred_at=timestamp)

    assert interrupted_ids == ["task-1"]
    assert collecting.state == "failed"
    assert collecting.phase == "interrupted"
    assert collecting.events_json[-1] == {
        "event_type": "process_restarted",
        "reason_code": "process_restarted",
        "checkpoint_id": None,
        "occurred_at": "2026-08-18T00:00:00Z",
    }
    assert completed.state == "completed"
    assert session.committed is True
    assert session.closed is True


class _FakeScalarResult:
    def __init__(self, records: list[ExplorationTaskRecord]) -> None:
        self._records = records

    def all(self) -> list[ExplorationTaskRecord]:
        return self._records


class _FakeSession:
    def __init__(self, records: list[ExplorationTaskRecord]) -> None:
        self._records = records
        self.committed = False
        self.closed = False

    def scalars(self, _statement: object) -> _FakeScalarResult:
        return _FakeScalarResult(
            [
                record
                for record in self._records
                if record.state not in {"completed", "partial", "failed", "cancelled"}
            ]
        )

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        raise AssertionError("recovery transaction should not roll back")

    def close(self) -> None:
        self.closed = True


def _record(*, task_id: str, state: str, phase: str) -> ExplorationTaskRecord:
    timestamp = datetime(2026, 8, 18, tzinfo=UTC)
    return ExplorationTaskRecord(
        task_id=task_id,
        state=state,
        phase=phase,
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
                "event_type": "task_created",
                "reason_code": None,
                "checkpoint_id": None,
                "occurred_at": "2026-08-18T00:00:00Z",
            }
        ],
        schema_version="1.0",
    )
