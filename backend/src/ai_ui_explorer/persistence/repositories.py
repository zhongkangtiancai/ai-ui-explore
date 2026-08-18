"""Repository codecs for strictly validated safe task projections."""

from pydantic import ValidationError

from ai_ui_explorer.persistence.models import ExplorationTaskRecord
from ai_ui_explorer.task_management.models import TaskSummary

_TASK_PROJECTION_SCHEMA_VERSION = "1.0"


class PersistenceProjectionError(RuntimeError):
    """A persisted projection cannot be safely exposed to a caller."""


def task_record_from_summary(summary: TaskSummary) -> ExplorationTaskRecord:
    """Project a public task summary into ORM fields without runtime handles."""
    return ExplorationTaskRecord(
        task_id=summary.task_id,
        state=str(summary.state),
        phase=summary.phase,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        redaction_count=summary.redaction_count,
        result_json=summary.result.model_dump(mode="json"),
        events_json=[event.model_dump(mode="json") for event in summary.events],
        schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
    )


def task_summary_from_record(record: ExplorationTaskRecord) -> TaskSummary:
    """Re-validate an untrusted database row before returning its public DTO."""
    if record.schema_version != _TASK_PROJECTION_SCHEMA_VERSION:
        raise PersistenceProjectionError("Persistence projection unavailable")
    try:
        return TaskSummary.model_validate(
            {
                "task_id": record.task_id,
                "state": record.state,
                "phase": record.phase,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "redaction_count": record.redaction_count,
                "events": record.events_json,
                "result": record.result_json,
            }
        )
    except ValidationError as error:
        raise PersistenceProjectionError("Persistence projection unavailable") from error
