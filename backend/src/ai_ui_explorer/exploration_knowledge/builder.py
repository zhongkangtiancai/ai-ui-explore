"""Deterministic Builder for bounded runtime exploration knowledge exports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import cast

from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.exploration_knowledge.models import (
    MAX_JSON_BYTES,
    ComparisonKnowledgeSource,
    DifferenceReliability,
    ExplorationKnowledgePackageV2,
    ExplorationKnowledgeSource,
    KnowledgeElement,
    KnowledgeEvidence,
    KnowledgeFact,
    KnowledgeGap,
    KnowledgeGapCode,
    KnowledgeIdentity,
    KnowledgeInteractionStep,
    KnowledgeLocatorCandidate,
    KnowledgeObservation,
    KnowledgePage,
    KnowledgeSource,
    KnowledgeVisibilityDifference,
    KnowledgeWorkflowEdge,
    KnowledgeWorkflowNode,
    TaskKnowledgeSource,
    original_evidence_key,
)
from ai_ui_explorer.permission_comparison.models import (
    ElementEvidence,
    EvidenceReference,
    PageEvidence,
)


class ExplorationKnowledgePackageTooLargeError(ValueError):
    """Raised when the fixed export byte budget would be exceeded."""


class ExplorationKnowledgeBuilder:
    """Build a package exclusively from already-redacted evidence projections."""

    def build(
        self,
        sources: list[ExplorationKnowledgeSource],
    ) -> ExplorationKnowledgePackageV2:
        ordered_sources = _sorted_unique_sources(sources)
        state = _BuildState()
        for source in ordered_sources:
            state.add_source(source)
        package = state.package()
        payload = json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_JSON_BYTES:
            raise ExplorationKnowledgePackageTooLargeError("knowledge package exceeds byte budget")
        return package


class _BuildState:
    def __init__(self) -> None:
        self.sources: list[KnowledgeSource] = []
        self.identities: list[KnowledgeIdentity] = []
        self.evidence: list[KnowledgeEvidence] = []
        self.pages: list[KnowledgePage] = []
        self.elements: list[KnowledgeElement] = []
        self.locator_candidates: list[KnowledgeLocatorCandidate] = []
        self.facts: list[KnowledgeFact] = []
        self.visibility_differences: list[KnowledgeVisibilityDifference] = []
        self.workflow_nodes: list[KnowledgeWorkflowNode] = []
        self.interaction_steps: list[KnowledgeInteractionStep] = []
        self.workflow_edges: list[KnowledgeWorkflowEdge] = []
        self.observations: list[KnowledgeObservation] = []
        self.knowledge_gaps: list[KnowledgeGap] = []
        self._evidence_ids: dict[tuple[str, tuple[str, str, str, str]], str] = {}
        self._workflow_incomplete = False

    def add_source(self, source: ExplorationKnowledgeSource) -> None:
        if isinstance(source, TaskKnowledgeSource):
            self._add_task(source)
            return
        self._add_comparison(source)

    def package(self) -> ExplorationKnowledgePackageV2:
        package_id = _id("exploration-package", *(item.source_id for item in self.sources))
        self._append_fixed_gap("package", "actions_not_explored")
        if not self.workflow_nodes and not self.workflow_edges:
            self._append_fixed_gap("package", "workflows_not_observed")
        if self._workflow_incomplete:
            self._append_fixed_gap("package", "workflows_partially_observed")
        self._append_fixed_gap("package", "evidence_process_local")
        return ExplorationKnowledgePackageV2(
            package_id=package_id,
            sources=self.sources,
            identities=self.identities,
            evidence=self.evidence,
            pages=self.pages,
            elements=self.elements,
            locator_candidates=self.locator_candidates,
            facts=self.facts,
            visibility_differences=self.visibility_differences,
            workflow_nodes=self.workflow_nodes,
            interaction_steps=self.interaction_steps,
            workflow_edges=self.workflow_edges,
            observations=self.observations,
            knowledge_gaps=self.knowledge_gaps,
            inferences=[],
        )

    def _add_task(self, source: TaskKnowledgeSource) -> None:
        self.sources.append(
            KnowledgeSource(
                source_id=source.source_id,
                source_kind="task",
                state=source.state,
                reason_codes=list(source.reason_codes),
            )
        )
        self._append_reason_gaps(source.source_id, source.reason_codes)
        if source.workflow is not None:
            self._add_workflow(source.source_id, source.workflow)
            self._workflow_incomplete = self._workflow_incomplete or (
                source.state != "completed"
                or any(step.status != "executed" for step in source.workflow.steps)
            )
        for ordinal, page in enumerate(source.pages, start=1):
            self._add_page(source.source_id, None, page, ordinal)

    def _add_workflow(self, source_ref: str, workflow: TaskWorkflowExport) -> None:
        workflow_export = workflow
        self.workflow_nodes.extend(
            KnowledgeWorkflowNode(state=node.state) for node in workflow_export.nodes
        )
        for step in workflow_export.steps:
            self.interaction_steps.append(
                KnowledgeInteractionStep(
                    step_id=_id("workflow-step", source_ref, step.step_id),
                    source_ref=source_ref,
                    kind=step.kind,
                    target_summary=step.target_summary,
                    before_state=step.before_state,
                    after_state=step.after_state,
                    status=step.status,
                    reason_code=step.reason_code,
                    evidence_refs=self._evidence_refs(source_ref, step.evidence_refs),
                )
            )
        for edge in workflow_export.edges:
            self.workflow_edges.append(
                KnowledgeWorkflowEdge(
                    edge_id=_id("workflow-edge", source_ref, edge.edge_id),
                    source_ref=source_ref,
                    source_state=edge.source_state,
                    target_state=edge.target_state,
                    kind=edge.kind,
                    observation_count=edge.observation_count,
                    evidence_refs=self._evidence_refs(source_ref, edge.evidence_refs),
                )
            )

    def _add_comparison(self, source: ComparisonKnowledgeSource) -> None:
        result = source.result
        self.sources.append(
            KnowledgeSource(
                source_id=source.source_id,
                source_kind="comparison",
                state=result.status,
                reason_codes=[],
            )
        )
        incomplete = result.status != "completed"
        for bundle in sorted(result.identities, key=lambda item: item.identity_id):
            identity_ref = _id("identity", source.source_id, bundle.identity_id)
            self.identities.append(
                KnowledgeIdentity(
                    identity_id=bundle.identity_id,
                    label=source.identity_labels.get(bundle.identity_id, bundle.identity_id),
                    source_ref=source.source_id,
                )
            )
            self._append_reason_gaps(identity_ref, bundle.reason_codes)
            for ordinal, page in enumerate(bundle.pages, start=1):
                self._add_page(source.source_id, identity_ref, page, ordinal)
            incomplete = incomplete or bundle.state != "completed"
        for difference in sorted(result.differences, key=lambda item: item.difference_id):
            evidence_refs = self._evidence_refs(source.source_id, difference.evidence_refs)
            reliability: DifferenceReliability = (
                "inconclusive" if incomplete else difference.reliability.value
            )
            difference_id = _id("difference", source.source_id, difference.difference_id)
            self.visibility_differences.append(
                KnowledgeVisibilityDifference(
                    difference_id=difference_id,
                    source_ref=source.source_id,
                    original_difference_id=difference.difference_id,
                    kind=difference.kind.value,
                    subject_key=difference.subject_key,
                    identity_states={
                        key: value.value
                        for key, value in sorted(difference.identity_states.items())
                    },
                    evidence_refs=evidence_refs,
                    reason_codes=list(difference.reason_codes),
                    reliability=reliability,
                )
            )
            if reliability == "inconclusive":
                self.observations.append(
                    KnowledgeObservation(
                        observation_id=_id("observation", difference_id),
                        subject_ref=difference_id,
                        code="visibility_difference_inconclusive",
                        evidence_refs=evidence_refs,
                        confidence=0.0,
                        limitations=["comparison is incomplete or not matchable"],
                    )
                )

    def _add_page(
        self,
        source_ref: str,
        identity_ref: str | None,
        page: PageEvidence,
        ordinal: int,
    ) -> None:
        page_id = _id("page", source_ref, identity_ref or "", page.page_key, str(ordinal))
        page_evidence = self._evidence_refs(source_ref, page.evidence_refs)
        self.pages.append(
            KnowledgePage(
                page_id=page_id,
                source_ref=source_ref,
                identity_ref=identity_ref,
                page_key=page.page_key,
                evidence_refs=page_evidence,
            )
        )
        self.facts.append(
            KnowledgeFact(
                fact_id=_id("fact", page_id, "page.observed"),
                subject_ref=page_id,
                predicate="page.observed",
                value=True,
                evidence_refs=page_evidence,
            )
        )
        for ordinal, element in enumerate(page.elements, start=1):
            element_id = _id("element", page_id, element.element_key, str(ordinal))
            evidence_refs = self._evidence_refs(source_ref, element.evidence_refs)
            self.elements.append(
                KnowledgeElement(
                    element_id=element_id,
                    page_ref=page_id,
                    frame_path=element.frame_path,
                    element_key=element.element_key,
                    tag=element.tag,
                    role=element.role,
                    accessible_name=element.accessible_name,
                    text=element.text,
                    attributes=dict(sorted(element.attributes.items())),
                    href=element.href,
                    visible=element.visible,
                    enabled=element.enabled,
                    evidence_refs=evidence_refs,
                )
            )
            self._add_element_facts(element_id, element, evidence_refs)
            for candidate in element.locator_candidates:
                self.locator_candidates.append(
                    KnowledgeLocatorCandidate(
                        locator_id=_id("locator", element_id, candidate.locator_id),
                        element_ref=element_id,
                        strategy=candidate.strategy,
                        parameters=dict(sorted(candidate.parameters.items())),
                        rank=candidate.rank,
                        recommended=candidate.recommended,
                        uniqueness=candidate.uniqueness,
                        stability=candidate.stability,
                        confidence=candidate.confidence,
                        frame_path=candidate.frame_path,
                        limitations=list(candidate.limitations),
                        evidence_refs=self._evidence_refs(source_ref, candidate.evidence_refs),
                    )
                )

    def _add_element_facts(
        self,
        element_id: str,
        element: ElementEvidence,
        evidence_refs: list[str],
    ) -> None:
        values = {
            "element.tag": element.tag,
            "element.role": element.role,
            "element.accessible_name": element.accessible_name,
            "element.text": element.text,
            "element.href": element.href,
            "element.visible": element.visible,
            "element.enabled": element.enabled,
        }
        for predicate, value in values.items():
            if value is not None:
                self.facts.append(
                    KnowledgeFact(
                        fact_id=_id("fact", element_id, predicate),
                        subject_ref=element_id,
                        predicate=predicate,
                        value=value,
                        evidence_refs=evidence_refs,
                    )
                )

    def _evidence_refs(
        self,
        source_ref: str,
        references: Iterable[EvidenceReference],
    ) -> list[str]:
        return [self._add_evidence(source_ref, reference) for reference in references]

    def _add_evidence(self, source_ref: str, reference: EvidenceReference) -> str:
        key = (source_ref, original_evidence_key(reference))
        if key in self._evidence_ids:
            return self._evidence_ids[key]
        evidence_id = _id("evidence", source_ref, *key[1])
        self._evidence_ids[key] = evidence_id
        self.evidence.append(
            KnowledgeEvidence(
                evidence_id=evidence_id,
                source_ref=source_ref,
                snapshot_id=reference.snapshot_id,
                snapshot_schema_version=reference.snapshot_schema_version,
                snapshot_sha256=reference.snapshot_sha256,
                json_pointer=reference.json_pointer,
                excerpt=reference.excerpt,
            )
        )
        return evidence_id

    def _append_reason_gaps(self, subject_ref: str, reason_codes: Iterable[str]) -> None:
        allowed = {
            "collection_truncated",
            "authentication_unverified",
            "collection_failed",
            "not_matchable",
        }
        for code in sorted(set(reason_codes).intersection(allowed)):
            self._append_fixed_gap(subject_ref, cast(KnowledgeGapCode, code))

    def _append_fixed_gap(self, subject_ref: str, code: KnowledgeGapCode) -> None:
        self.knowledge_gaps.append(
            KnowledgeGap(
                gap_id=_id("gap", subject_ref, code),
                subject_ref=subject_ref,
                code=code,
                limitations=[code.replace("_", " ")],
            )
        )


def _sorted_unique_sources(
    sources: list[ExplorationKnowledgeSource],
) -> list[ExplorationKnowledgeSource]:
    by_id = {source.source_id: source for source in sources}
    if len(by_id) != len(sources):
        raise ValueError("knowledge package source IDs must be unique")
    return [by_id[source_id] for source_id in sorted(by_id)]


def _id(prefix: str, *parts: str) -> str:
    normalized = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(normalized).hexdigest()[:16]}"
