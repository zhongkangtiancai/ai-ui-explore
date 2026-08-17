"""Contract tests for the deterministic unified exploration knowledge Builder."""

import json
from pathlib import Path

import pytest

from ai_ui_explorer.exploration.workflows import (
    InteractionStepView,
    TaskWorkflowExport,
    WorkflowEdgeView,
    WorkflowNodeView,
)
from ai_ui_explorer.exploration_knowledge.builder import (
    ExplorationKnowledgeBuilder,
    ExplorationKnowledgePackageTooLargeError,
)
from ai_ui_explorer.exploration_knowledge.models import (
    ComparisonKnowledgeSource,
    ExplorationKnowledgePackageV2,
    TaskKnowledgeSource,
)
from ai_ui_explorer.permission_comparison.models import (
    DifferenceKind,
    ElementEvidence,
    EvidenceReference,
    IdentityEvidenceBundle,
    IdentityRunState,
    ObservationState,
    PageEvidence,
    PermissionComparisonResult,
    VisibilityDifference,
)


def _evidence(pointer: str = "/frames/0/elements/0") -> EvidenceReference:
    return EvidenceReference(
        evidence_id="evidence-1",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer=pointer,
        excerpt="safe observed element",
    )


def _page(page_key: str) -> PageEvidence:
    evidence = _evidence()
    return PageEvidence(
        page_key=page_key,
        elements=[
            ElementEvidence(
                element_key="button:save",
                frame_path="main",
                tag="button",
                role="button",
                accessible_name="保存",
                text="保存",
                attributes={"type": "button"},
                href=None,
                visible=True,
                enabled=True,
                evidence_refs=[evidence],
            )
        ],
        evidence_refs=[evidence],
    )


def _task_source() -> TaskKnowledgeSource:
    return TaskKnowledgeSource(
        source_id="task-1",
        state="completed",
        pages=[_page("https://app.example.test/home")],
        reason_codes=[],
    )


def _comparison_source() -> ComparisonKnowledgeSource:
    page = _page("https://app.example.test/home")
    evidence = _evidence("/frames/0")
    return ComparisonKnowledgeSource(
        source_id="comparison-1",
        result=PermissionComparisonResult(
            comparison_id="comparison-1",
            status="partial",
            identities=[
                IdentityEvidenceBundle(
                    identity_id="identity-1",
                    state=IdentityRunState.COMPLETED,
                    pages=[page],
                    reason_codes=[],
                ),
                IdentityEvidenceBundle(
                    identity_id="identity-2",
                    state=IdentityRunState.PARTIAL,
                    pages=[],
                    reason_codes=["collection_truncated"],
                ),
            ],
            differences=[
                VisibilityDifference(
                    difference_id="difference-1",
                    kind=DifferenceKind.OBSERVED_IN_ONLY_ONE_IDENTITY,
                    subject_key="page:https://app.example.test/home",
                    identity_states={
                        "identity-1": ObservationState.OBSERVED,
                        "identity-2": ObservationState.COLLECTION_INCOMPLETE,
                    },
                    evidence_refs=[evidence],
                    reason_codes=["collection_truncated"],
                )
            ],
        ),
    )


def test_builder_combines_task_and_comparison_without_merging_same_page_keys() -> None:
    package = ExplorationKnowledgeBuilder().build([_comparison_source(), _task_source()])

    assert package.schema_version == "2.0"
    assert [source.source_id for source in package.sources] == ["comparison-1", "task-1"]
    assert len(package.pages) == 2
    assert len({page.page_id for page in package.pages}) == 2
    assert package.inferences == []
    assert any(gap.code == "evidence_process_local" for gap in package.knowledge_gaps)


def test_builder_is_deterministic_and_marks_partial_differences_inconclusive() -> None:
    builder = ExplorationKnowledgeBuilder()

    first = builder.build([_task_source(), _comparison_source()]).model_dump_json()
    package = builder.build([_comparison_source(), _task_source()])

    assert package.model_dump_json() == first
    assert package.visibility_differences[0].reliability == "inconclusive"


def test_builder_emits_only_resolvable_evidence_for_facts_and_locators() -> None:
    package = ExplorationKnowledgeBuilder().build([_task_source()])
    evidence_ids = {item.evidence_id for item in package.evidence}

    assert all(set(fact.evidence_refs) <= evidence_ids for fact in package.facts)
    assert all(set(locator.evidence_refs) <= evidence_ids for locator in package.locator_candidates)
    assert json.loads(package.model_dump_json())["inferences"] == []


def test_builder_exports_verified_readonly_workflow_without_inference() -> None:
    before_state = "a" * 64
    after_state = "b" * 64
    source = _task_source().model_copy(
        update={
            "workflow": TaskWorkflowExport(
                task_id="task-1",
                state="completed",
                steps=[
                    InteractionStepView(
                        step_id="step-" + "1" * 16,
                        kind="open_menu",
                        target_summary="安全菜单",
                        before_state=before_state,
                        after_state=after_state,
                        status="executed",
                        reason_code="executed",
                        evidence_refs=[_evidence()],
                    )
                ],
                nodes=[WorkflowNodeView(state=before_state), WorkflowNodeView(state=after_state)],
                edges=[
                    WorkflowEdgeView(
                        edge_id="edge-" + "2" * 16,
                        source_state=before_state,
                        target_state=after_state,
                        kind="open_menu",
                        observation_count=1,
                        evidence_refs=[_evidence()],
                    )
                ],
            )
        }
    )

    package = ExplorationKnowledgeBuilder().build([source])

    assert [node.state for node in package.workflow_nodes] == [before_state, after_state]
    assert package.interaction_steps[0].kind == "open_menu"
    assert package.workflow_edges[0].observation_count == 1
    assert set(package.interaction_steps[0].evidence_refs) <= {
        item.evidence_id for item in package.evidence
    }
    assert package.inferences == []
    assert not any(gap.code == "workflows_not_observed" for gap in package.knowledge_gaps)


def test_builder_marks_partial_workflow_as_incomplete() -> None:
    source = _task_source().model_copy(
        update={
            "state": "partial",
            "workflow": TaskWorkflowExport(
                task_id="task-1",
                state="partial",
                steps=[],
                nodes=[],
                edges=[],
            ),
        }
    )

    package = ExplorationKnowledgeBuilder().build([source])

    assert any(gap.code == "workflows_partially_observed" for gap in package.knowledge_gaps)


def test_builder_rejects_package_over_the_fixed_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_ui_explorer.exploration_knowledge.builder.MAX_JSON_BYTES",
        1,
    )

    with pytest.raises(ExplorationKnowledgePackageTooLargeError):
        ExplorationKnowledgeBuilder().build([_task_source()])


def test_committed_v2_schema_matches_the_package_model() -> None:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "ai_ui_explorer"
        / "exploration_knowledge"
        / "schema"
        / "exploration-knowledge-package-v2.schema.json"
    )

    assert json.loads(schema_path.read_text(encoding="utf-8")) == (
        ExplorationKnowledgePackageV2.to_schema()
    )
