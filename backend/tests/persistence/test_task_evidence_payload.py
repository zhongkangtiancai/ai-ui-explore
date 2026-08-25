from ai_ui_explorer.permission_comparison.models import EvidenceReference, PageEvidence
from ai_ui_explorer.persistence.dtos import (
    PersistedTaskPageEvidence,
    TaskEvidencePersistencePayload,
)
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport, TaskPageView


def test_task_evidence_persistence_payload_keeps_redacted_page_detail() -> None:
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

    assert payload.pages[0].page.page_key == "origin-1/path"


def test_task_evidence_persistence_payload_rejects_page_not_in_export() -> None:
    reference = EvidenceReference(
        evidence_id="evidence-1",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer="/frames/0",
        excerpt="safe",
    )
    export = ExplorationEvidenceExport(
        schema_version="1.0",
        task_id="task-1",
        state="completed",
    )

    try:
        TaskEvidencePersistencePayload(
            export=export,
            pages=[
                PersistedTaskPageEvidence(
                    page_id="page-1",
                    page=PageEvidence(
                        page_key="origin-1/path",
                        evidence_refs=[reference],
                    ),
                )
            ],
        )
    except ValueError as error:
        assert "page IDs" in str(error)
    else:
        raise AssertionError("unindexed page detail must be rejected")
