from datetime import UTC, datetime

from ai_ui_explorer.persistence.models import (
    ExplorationTaskRecord,
    PermissionComparisonRecord,
)
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def test_repository_lists_only_valid_terminal_task_summaries() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(
            task_records=[
                _task_record("task-2", "collecting"),
                _task_record("task-1", "completed"),
            ],
            comparison_records=[],
        )  # type: ignore[arg-type]
    )

    assert [summary.task_id for summary in repository.list_terminal_task_summaries()] == ["task-1"]


def test_repository_lists_only_valid_terminal_comparison_views() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(
            task_records=[],
            comparison_records=[
                _comparison_record("comparison-2", "collecting"),
                _comparison_record("comparison-1", "completed"),
            ],
        )  # type: ignore[arg-type]
    )

    assert [view.comparison_id for view in repository.list_terminal_comparison_views()] == [
        "comparison-1"
    ]


class _FakeScalarResult[T]:
    def __init__(self, records: list[T]) -> None:
        self._records = records

    def all(self) -> list[T]:
        return self._records


class _FakeSession:
    def __init__(
        self,
        *,
        task_records: list[ExplorationTaskRecord],
        comparison_records: list[PermissionComparisonRecord],
    ) -> None:
        self._task_records = task_records
        self._comparison_records = comparison_records

    def scalars[T](self, statement: object) -> _FakeScalarResult[T]:
        source = str(statement)
        records: object = (
            self._task_records if "exploration_tasks" in source else self._comparison_records
        )
        return _FakeScalarResult(records)  # type: ignore[arg-type]

    def close(self) -> None:
        pass


def _task_record(task_id: str, state: str) -> ExplorationTaskRecord:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return ExplorationTaskRecord(
        task_id=task_id,
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
        events_json=[{"event_type": "task_completed", "occurred_at": "2026-08-19T00:00:00Z"}],
        schema_version="1.0",
    )


def _comparison_record(comparison_id: str, state: str) -> PermissionComparisonRecord:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return PermissionComparisonRecord(
        comparison_id=comparison_id,
        state=state,
        created_at=timestamp,
        updated_at=timestamp,
        identities_json={"identity-1": "completed", "identity-2": "completed"},
        result_json={
            "comparison_id": comparison_id,
            "status": "completed",
            "identities": [
                {"identity_id": "identity-1", "state": "completed", "pages": []},
                {"identity_id": "identity-2", "state": "completed", "pages": []},
            ],
            "differences": [],
        },
        schema_version="1.0",
    )
