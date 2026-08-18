from datetime import UTC, datetime

import pytest

from ai_ui_explorer.persistence.models import ExplorationTaskRecord
from ai_ui_explorer.persistence.repositories import (
    PersistenceProjectionError,
    task_record_from_summary,
    task_summary_from_record,
)
from ai_ui_explorer.task_management.models import (
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)


def test_task_projection_round_trips_only_public_summary_fields() -> None:
    summary = _summary()

    record = task_record_from_summary(summary)

    assert record.task_id == "task-1"
    assert record.result_json == summary.result.model_dump(mode="json")
    assert task_summary_from_record(record) == summary


def test_task_projection_rejects_invalid_persisted_json_without_returning_payload() -> None:
    record = ExplorationTaskRecord(
        task_id="task-1",
        state="completed",
        phase="completed",
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
        updated_at=datetime(2026, 8, 18, tzinfo=UTC),
        redaction_count=0,
        result_json={"source_summary": "token=must-not-disclose"},
        events_json=[],
        schema_version="1.0",
    )

    with pytest.raises(
        PersistenceProjectionError,
        match="Persistence projection unavailable",
    ) as error:
        task_summary_from_record(record)

    assert "must-not-disclose" not in str(error.value)


def _summary() -> TaskSummary:
    timestamp = datetime(2026, 8, 18, tzinfo=UTC)
    return TaskSummary(
        task_id="task-1",
        state="completed",
        phase="completed",
        created_at=timestamp,
        updated_at=timestamp,
        redaction_count=0,
        events=[TaskEventView(event_type="task_completed", occurred_at=timestamp)],
        result=TaskResultSummary(
            page_count=1,
            element_count=2,
            link_count=3,
            source_summary="redacted source",
        ),
    )
