"""Tests for process-local, bounded task evidence."""

from ai_ui_explorer.exploration.interactions import (
    ReadonlyInteractionCandidate,
    ReadonlyInteractionExecution,
)
from ai_ui_explorer.exploration.queue import ExplorationTarget
from ai_ui_explorer.exploration.runner import (
    ExplorationRunResult,
    ReadonlyInteractionStep,
)
from ai_ui_explorer.exploration.state import StateFingerprint
from ai_ui_explorer.permission_comparison.models import EvidenceReference, LocatorCandidateEvidence
from ai_ui_explorer.task_management.evidence import TaskEvidenceCollector
from tests.snapshot.factories import make_element, make_frame, make_snapshot


def _target(url: str) -> ExplorationTarget:
    return ExplorationTarget(
        url=url,
        depth=0,
        source_url=None,
        module_id="dashboard",
        action_type="module_entry",
        label="Dashboard",
    )


def test_task_evidence_collector_keeps_projected_pages_after_partial_run() -> None:
    collector = TaskEvidenceCollector()
    projected = collector.record(
        _target("https://app.example.test/one?token=source-secret"),
        make_snapshot(
            frames=[
                make_frame(
                    elements=[
                        make_element(
                            element_id="help-link",
                            tag="a",
                            href="https://app.example.test/help?token=href-secret",
                        )
                    ]
                )
            ]
        ),
    )

    collector.complete(
        ExplorationRunResult(
            status="partial",
            visits=[],
            enqueue_decisions=[],
            errors=[],
            stop_reasons=["collector_failure"],
        )
    )

    pages = collector.pages()
    assert projected == collector.page_detail("page-1")
    assert projected is not None
    assert not hasattr(projected, "snapshot")
    assert [page.page_id for page in pages] == ["page-1"]
    assert pages[0].page_key != "https://app.example.test/one?token=source-secret"
    assert pages[0].frame_count == 1
    assert pages[0].element_count == 1
    assert pages[0].link_count == 1
    assert pages[0].reason_codes == ["collector_failure"]


def test_task_evidence_detail_and_export_do_not_expose_snapshot_or_browser() -> None:
    collector = TaskEvidenceCollector()
    collector.record(
        _target("https://app.example.test/one"),
        make_snapshot(
            frames=[
                make_frame(
                    elements=[make_element(attributes={"data-note": "password=fixture-secret"})]
                )
            ]
        ),
    )
    detail = collector.page_detail("page-1")
    exported = collector.export(
        task_id="task-1",
        state="completed",
    )

    assert detail is not None
    assert not hasattr(detail, "snapshot")
    payload = exported.model_dump_json().lower()
    assert "fixture-secret" not in payload
    assert "snapshotdocument" not in payload
    assert "browser" not in payload


def test_task_evidence_export_keeps_fixed_readonly_interaction_stop_reason() -> None:
    """Dropping this reason would hide a bounded, incomplete task outcome."""
    collector = TaskEvidenceCollector()
    collector.complete(
        ExplorationRunResult(
            status="partial",
            visits=[],
            enqueue_decisions=[],
            errors=[],
            stop_reasons=["interaction_budget_exhausted"],
        )
    )

    exported = collector.export(task_id="task-1", state="partial")

    assert exported.reason_codes == ["interaction_budget_exhausted"]


def test_task_evidence_collector_merges_verified_workflow_edges() -> None:
    """A missing evidence projection or unstable merge must fail this public contract."""
    collector = TaskEvidenceCollector()
    step = _verified_interaction_step()
    collector.complete(
        ExplorationRunResult(
            status="completed",
            visits=[],
            enqueue_decisions=[],
            errors=[],
            stop_reasons=[],
            interaction_steps=[step, step],
        )
    )

    workflow = collector.workflow(task_id="task-1", state="completed")

    assert len(workflow.steps) == 2
    assert len(workflow.edges) == 1
    assert workflow.edges[0].kind == "switch_tab"
    assert workflow.edges[0].observation_count == 2


def _verified_interaction_step() -> ReadonlyInteractionStep:
    candidate = ReadonlyInteractionCandidate(
        kind="switch_tab",
        element_key="details-tab",
        frame_path="main",
        target_summary="详情",
        locator=LocatorCandidateEvidence(
            locator_id="details-tab",
            strategy="id",
            parameters={"value": "details-tab"},
            source="generated",
            uniqueness="unique",
            stability="high",
            confidence=1.0,
            rank=1,
            recommended=True,
            frame_path="main",
            evidence_refs=[
                EvidenceReference(
                    evidence_id="evidence-details-tab",
                    snapshot_id="snapshot-1",
                    snapshot_schema_version="1.1",
                    snapshot_sha256="a" * 64,
                    json_pointer="/frames/0",
                    excerpt="safe",
                )
            ],
        ),
    )
    return ReadonlyInteractionStep(
        candidate=candidate,
        execution=ReadonlyInteractionExecution(
            status="executed",
            reason_code="executed",
            safe_message="Interaction executed.",
            url_before="https://app.example.test/root",
            url_after="https://app.example.test/root",
        ),
        before_state=StateFingerprint(fingerprint="a" * 64, seen_before=False, truncated=False),
        after_state=StateFingerprint(fingerprint="b" * 64, seen_before=False, truncated=False),
    )
