from datetime import UTC, datetime

import pytest

from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.permission_comparison.models import EvidenceReference, PageEvidence
from ai_ui_explorer.persistence.dtos import PersistedTaskPageEvidence
from ai_ui_explorer.persistence.models import (
    ExplorationKnowledgeSourceRecord,
    ExplorationTaskRecord,
    TaskEvidenceExportRecord,
    TaskWorkflowRecord,
)
from ai_ui_explorer.persistence.repositories import (
    PersistenceProjectionError,
    SafeTaskRepository,
)
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport, TaskPageView
from ai_ui_explorer.task_management.models import (
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)


def test_repository_persists_terminal_task_projection_in_one_transaction() -> None:
    session = _FakeSession()
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    summary = _summary(state="completed", phase="completed")

    repository.persist_terminal_task(
        summary=summary,
        evidence=ExplorationEvidenceExport(
            schema_version="1.0",
            task_id="task-1",
            state="completed",
            result=summary.result,
        ),
        workflow=TaskWorkflowExport(task_id="task-1", state="completed"),
    )

    assert [type(record) for record in session.merged] == [
        ExplorationTaskRecord,
        TaskEvidenceExportRecord,
        TaskWorkflowRecord,
        ExplorationKnowledgeSourceRecord,
    ]
    assert session.committed is True
    assert session.closed is True


def test_repository_persists_page_details_with_terminal_evidence_export() -> None:
    session = _FakeSession()
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    summary = _summary(state="completed", phase="completed")
    reference = EvidenceReference(
        evidence_id="evidence-1",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer="/frames/0",
        excerpt="safe",
    )

    repository.persist_terminal_task(
        summary=summary,
        evidence=ExplorationEvidenceExport(
            schema_version="1.0",
            task_id="task-1",
            state="completed",
            pages=[
                TaskPageView(
                    page_id="page-1",
                    page_key="origin-1/path",
                    frame_count=1,
                    element_count=0,
                    link_count=0,
                    status="observed",
                    evidence_refs=[reference],
                )
            ],
        ),
        pages=[
            PersistedTaskPageEvidence(
                page_id="page-1",
                page=PageEvidence(
                    page_key="origin-1/path",
                    evidence_refs=[reference],
                ),
            )
        ],
        workflow=TaskWorkflowExport(task_id="task-1", state="completed"),
    )

    persisted = next(
        record for record in session.merged if isinstance(record, TaskEvidenceExportRecord)
    )
    assert persisted.payload["pages"][0]["page_id"] == "page-1"
    assert persisted.payload["export"]["pages"][0]["page_id"] == "page-1"


def test_repository_rejects_nonterminal_task_without_opening_transaction() -> None:
    session = _FakeSession()
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    summary = _summary(state="collecting", phase="collecting")

    with pytest.raises(PersistenceProjectionError, match="Persistence projection unavailable"):
        repository.persist_terminal_task(
            summary=summary,
            evidence=ExplorationEvidenceExport(
                schema_version="1.0",
                task_id="task-1",
                state="completed",
            ),
            workflow=TaskWorkflowExport(task_id="task-1", state="completed"),
        )

    assert session.merged == []
    assert session.committed is False


class _FakeSession:
    def __init__(self) -> None:
        self.merged: list[object] = []
        self.committed = False
        self.closed = False

    def merge(self, record: object) -> object:
        self.merged.append(record)
        return record

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        raise AssertionError("terminal projection should not roll back")

    def close(self) -> None:
        self.closed = True


def _summary(*, state: str, phase: str) -> TaskSummary:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return TaskSummary(
        task_id="task-1",
        state=state,
        phase=phase,
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
