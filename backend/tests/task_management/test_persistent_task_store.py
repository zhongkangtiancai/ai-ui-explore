from datetime import UTC, datetime

from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.permission_comparison.models import EvidenceReference, PageEvidence
from ai_ui_explorer.persistence.dtos import PersistedTaskPageEvidence
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport, TaskPageView
from ai_ui_explorer.task_management.models import TaskResultSummary, TaskSummary
from ai_ui_explorer.task_management.persistence import PersistentTaskProjectionStore


def test_store_projects_terminal_collector_data_before_repository_write() -> None:
    repository = _RecordingRepository()
    store = PersistentTaskProjectionStore(repository=repository)  # type: ignore[arg-type]

    store.persist_terminal(summary=_summary(), collector=_Collector())  # type: ignore[arg-type]

    assert repository.summary.task_id == "task-1"
    assert repository.pages == [
        PersistedTaskPageEvidence(
            page_id="page-1",
            page=PageEvidence(
                page_key="origin-1/path",
                evidence_refs=[_reference()],
            ),
        )
    ]


class _RecordingRepository:
    def persist_terminal_task(
        self,
        *,
        summary: TaskSummary,
        evidence: ExplorationEvidenceExport,
        workflow: TaskWorkflowExport,
        pages: list[PersistedTaskPageEvidence],
    ) -> None:
        self.summary = summary
        self.evidence = evidence
        self.workflow = workflow
        self.pages = pages


class _Collector:
    def pages(self) -> list[TaskPageView]:
        return [
            TaskPageView(
                page_id="page-1",
                page_key="origin-1/path",
                frame_count=1,
                element_count=0,
                link_count=0,
                status="observed",
                evidence_refs=[_reference()],
            )
        ]

    def page_detail(self, page_id: str) -> PageEvidence | None:
        return (
            PageEvidence(page_key="origin-1/path", evidence_refs=[_reference()])
            if page_id == "page-1"
            else None
        )

    def export(
        self,
        *,
        task_id: str,
        state: str,
        result: TaskResultSummary,
    ) -> ExplorationEvidenceExport:
        return ExplorationEvidenceExport(
            schema_version="1.0",
            task_id=task_id,
            state=state,
            result=result,
            pages=self.pages(),
        )

    def workflow(self, *, task_id: str, state: str) -> TaskWorkflowExport:
        return TaskWorkflowExport(task_id=task_id, state=state)


def _summary() -> TaskSummary:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return TaskSummary(
        task_id="task-1",
        state="completed",
        phase="completed",
        created_at=timestamp,
        updated_at=timestamp,
        redaction_count=0,
        events=[],
        result=TaskResultSummary(
            page_count=1,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
    )


def _reference() -> EvidenceReference:
    return EvidenceReference(
        evidence_id="evidence-1",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer="/frames/0",
        excerpt="safe",
    )
