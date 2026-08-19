from datetime import UTC, datetime

from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.permission_comparison.models import EvidenceReference, PageEvidence
from ai_ui_explorer.persistence.dtos import (
    PersistedTaskPageEvidence,
    TaskEvidencePersistencePayload,
)
from ai_ui_explorer.persistence.models import (
    ExplorationTaskRecord,
    TaskEvidenceExportRecord,
    TaskWorkflowRecord,
)
from ai_ui_explorer.persistence.repositories import SafeTaskRepository
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport, TaskPageView


def test_repository_rebuilds_terminal_task_knowledge_source_from_safe_records() -> None:
    reference = EvidenceReference(
        evidence_id="evidence-1",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer="/frames/0",
        excerpt="safe",
    )
    payload = TaskEvidencePersistencePayload(
        export=ExplorationEvidenceExport(
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
                page=PageEvidence(page_key="origin-1/path", evidence_refs=[reference]),
            )
        ],
    )
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(
            task=_task_record(),
            evidence=TaskEvidenceExportRecord(
                task_id="task-1",
                payload=payload.model_dump(mode="json"),
                schema_version="1.0",
            ),
            workflow=TaskWorkflowRecord(
                task_id="task-1",
                payload=TaskWorkflowExport(
                    task_id="task-1", state="completed"
                ).model_dump(mode="json"),
                schema_version="1.0",
            ),
        )  # type: ignore[arg-type]
    )

    source = repository.get_terminal_task_knowledge_source("task-1")

    assert source is not None
    assert source.source_id == "task-1"
    assert source.pages[0].page_key == "origin-1/path"
    assert source.workflow is not None


class _FakeSession:
    def __init__(
        self,
        *,
        task: ExplorationTaskRecord,
        evidence: TaskEvidenceExportRecord,
        workflow: TaskWorkflowRecord,
    ) -> None:
        self._records = {
            ExplorationTaskRecord: task,
            TaskEvidenceExportRecord: evidence,
            TaskWorkflowRecord: workflow,
        }

    def get(self, model: object, task_id: str) -> object | None:
        record = self._records.get(model)
        return record if task_id == "task-1" else None

    def close(self) -> None:
        pass


def _task_record() -> ExplorationTaskRecord:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return ExplorationTaskRecord(
        task_id="task-1",
        state="completed",
        phase="completed",
        created_at=timestamp,
        updated_at=timestamp,
        redaction_count=0,
        result_json={
            "page_count": 1,
            "element_count": 0,
            "link_count": 0,
            "source_summary": "redacted source",
        },
        events_json=[],
        schema_version="1.0",
    )
