"""Strict, process-local models for unified exploration knowledge exports."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import (
    EvidenceReference,
    PageEvidence,
    PermissionComparisonResult,
)

MAX_SOURCES = 5
MAX_PAGES = 500
MAX_ELEMENTS = 20_000
MAX_DIFFERENCES = 20_000
MAX_EVIDENCE = 50_000
MAX_JSON_BYTES = 10 * 1024 * 1024

type TerminalState = Literal["completed", "partial", "failed", "cancelled"]
type DifferenceReliability = Literal["high", "medium", "low", "inconclusive"]
type KnowledgeGapCode = Literal[
    "collection_truncated",
    "authentication_unverified",
    "collection_failed",
    "not_matchable",
    "actions_not_explored",
    "workflows_not_observed",
    "workflows_partially_observed",
    "evidence_process_local",
]


class TaskKnowledgeSource(DeepFrozenModel):
    """One terminal task's already-redacted evidence projection."""

    source_id: str = Field(pattern=r"^task-[0-9]{1,20}$")
    state: TerminalState
    pages: list[PageEvidence] = Field(default_factory=list, max_length=100)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    workflow: TaskWorkflowExport | None = None


class ComparisonKnowledgeSource(DeepFrozenModel):
    """One terminal comparison result plus non-sensitive identity labels."""

    source_id: str = Field(pattern=r"^comparison-[0-9]{1,20}$")
    result: PermissionComparisonResult
    identity_labels: dict[str, str] = Field(default_factory=dict, max_length=5)

    @model_validator(mode="after")
    def require_matching_source_id(self) -> Self:
        if self.source_id != self.result.comparison_id:
            raise ValueError("comparison source ID must match comparison result")
        return self


type ExplorationKnowledgeSource = TaskKnowledgeSource | ComparisonKnowledgeSource


class KnowledgeSource(DeepFrozenModel):
    source_id: str = Field(min_length=1, max_length=40)
    source_kind: Literal["task", "comparison"]
    state: TerminalState
    reason_codes: list[str] = Field(default_factory=list, max_length=50)


class KnowledgeIdentity(DeepFrozenModel):
    identity_id: str = Field(pattern=r"^identity-[0-9]{1,20}$")
    label: str = Field(min_length=1, max_length=80)
    source_ref: str = Field(min_length=1, max_length=40)


class KnowledgeEvidence(DeepFrozenModel):
    evidence_id: str = Field(pattern=r"^evidence-[a-f0-9]{16}$")
    source_ref: str = Field(min_length=1, max_length=40)
    snapshot_id: str = Field(min_length=1, max_length=120)
    snapshot_schema_version: Literal["1.0", "1.1"]
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    json_pointer: str = Field(min_length=1, max_length=1_024)
    excerpt: str = Field(min_length=1, max_length=500)


class KnowledgePage(DeepFrozenModel):
    page_id: str = Field(pattern=r"^page-[a-f0-9]{16}$")
    source_ref: str = Field(min_length=1, max_length=40)
    identity_ref: str | None = Field(default=None, max_length=40)
    page_key: str = Field(min_length=1, max_length=2_048)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)


class KnowledgeElement(DeepFrozenModel):
    element_id: str = Field(pattern=r"^element-[a-f0-9]{16}$")
    page_ref: str = Field(min_length=1, max_length=40)
    frame_path: str = Field(min_length=1, max_length=500)
    element_key: str = Field(min_length=1, max_length=300)
    tag: str = Field(min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=120)
    accessible_name: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=500)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=32)
    href: str | None = Field(default=None, max_length=2_048)
    visible: bool | None = None
    enabled: bool | None = None
    evidence_refs: list[str] = Field(min_length=1, max_length=12)


class KnowledgeLocatorCandidate(DeepFrozenModel):
    locator_id: str = Field(pattern=r"^locator-[a-f0-9]{16}$")
    element_ref: str = Field(min_length=1, max_length=40)
    strategy: str = Field(min_length=1, max_length=32)
    parameters: dict[str, str | bool | int | float] = Field(max_length=8)
    rank: int = Field(ge=1)
    recommended: bool
    uniqueness: str = Field(min_length=1, max_length=32)
    stability: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)
    frame_path: str = Field(min_length=1, max_length=500)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    evidence_refs: list[str] = Field(min_length=1, max_length=2)


class KnowledgeFact(DeepFrozenModel):
    fact_id: str = Field(pattern=r"^fact-[a-f0-9]{16}$")
    subject_ref: str = Field(min_length=1, max_length=40)
    predicate: str = Field(min_length=1, max_length=120)
    value: str | bool | int | float | None = None
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    confidence: float = Field(default=1.0, ge=1.0, le=1.0)
    assertion_type: Literal["observed"] = "observed"


class KnowledgeObservation(DeepFrozenModel):
    observation_id: str = Field(pattern=r"^observation-[a-f0-9]{16}$")
    subject_ref: str = Field(min_length=1, max_length=40)
    code: Literal["visibility_difference_inconclusive"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(min_length=1, max_length=20)


class KnowledgeGap(DeepFrozenModel):
    gap_id: str = Field(pattern=r"^gap-[a-f0-9]{16}$")
    subject_ref: str = Field(min_length=1, max_length=40)
    code: KnowledgeGapCode
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(min_length=1, max_length=20)


class KnowledgeVisibilityDifference(DeepFrozenModel):
    difference_id: str = Field(pattern=r"^difference-[a-f0-9]{16}$")
    source_ref: str = Field(min_length=1, max_length=40)
    original_difference_id: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=80)
    subject_key: str = Field(min_length=1, max_length=2_048)
    identity_states: dict[str, str] = Field(min_length=2, max_length=5)
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    reliability: DifferenceReliability


class KnowledgeWorkflowNode(DeepFrozenModel):
    """A verified observed page-state fingerprint in a readonly workflow."""

    state: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeInteractionStep(DeepFrozenModel):
    """One redacted readonly interaction observation, never a replay instruction."""

    step_id: str = Field(pattern=r"^workflow-step-[a-f0-9]{16}$")
    source_ref: str = Field(min_length=1, max_length=40)
    kind: str = Field(min_length=1, max_length=32)
    target_summary: str = Field(min_length=1, max_length=500)
    before_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_state: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: str = Field(min_length=1, max_length=32)
    reason_code: str = Field(min_length=1, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)


class KnowledgeWorkflowEdge(DeepFrozenModel):
    """A merged transition that was verified by one or more readonly steps."""

    edge_id: str = Field(pattern=r"^workflow-edge-[a-f0-9]{16}$")
    source_ref: str = Field(min_length=1, max_length=40)
    source_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str = Field(min_length=1, max_length=32)
    observation_count: int = Field(ge=1)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)


class ExplorationKnowledgePackageV2(DeepFrozenModel):
    """A bounded, downloadable runtime knowledge package with no inference."""

    schema_version: Literal["2.0"] = "2.0"
    package_id: str = Field(pattern=r"^exploration-package-[a-f0-9]{16}$")
    sources: list[KnowledgeSource] = Field(min_length=1, max_length=MAX_SOURCES)
    identities: list[KnowledgeIdentity] = Field(default_factory=list, max_length=25)
    evidence: list[KnowledgeEvidence] = Field(default_factory=list, max_length=MAX_EVIDENCE)
    pages: list[KnowledgePage] = Field(default_factory=list, max_length=MAX_PAGES)
    elements: list[KnowledgeElement] = Field(default_factory=list, max_length=MAX_ELEMENTS)
    locator_candidates: list[KnowledgeLocatorCandidate] = Field(
        default_factory=list,
        max_length=MAX_ELEMENTS * 12,
    )
    facts: list[KnowledgeFact] = Field(default_factory=list, max_length=MAX_ELEMENTS * 8)
    visibility_differences: list[KnowledgeVisibilityDifference] = Field(
        default_factory=list,
        max_length=MAX_DIFFERENCES,
    )
    workflow_nodes: list[KnowledgeWorkflowNode] = Field(default_factory=list, max_length=5_000)
    interaction_steps: list[KnowledgeInteractionStep] = Field(
        default_factory=list, max_length=5_000
    )
    workflow_edges: list[KnowledgeWorkflowEdge] = Field(default_factory=list, max_length=5_000)
    observations: list[KnowledgeObservation] = Field(
        default_factory=list,
        max_length=MAX_DIFFERENCES,
    )
    knowledge_gaps: list[KnowledgeGap] = Field(
        default_factory=list,
        max_length=MAX_DIFFERENCES,
    )
    inferences: list[object] = Field(default_factory=list, max_length=0)

    @model_validator(mode="after")
    def require_resolvable_evidence_and_empty_inferences(self) -> Self:
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("knowledge evidence IDs must be unique")
        references = [
            *[item.evidence_refs for item in self.pages],
            *[item.evidence_refs for item in self.elements],
            *[item.evidence_refs for item in self.locator_candidates],
            *[item.evidence_refs for item in self.facts],
            *[item.evidence_refs for item in self.visibility_differences],
            *[item.evidence_refs for item in self.workflow_edges],
            *[item.evidence_refs for item in self.interaction_steps],
            *[item.evidence_refs for item in self.observations],
            *[item.evidence_refs for item in self.knowledge_gaps],
        ]
        if any(not set(values) <= evidence_ids for values in references):
            raise ValueError("knowledge evidence references must resolve inside package")
        if self.inferences:
            raise ValueError("runtime package cannot contain inferences")
        return self

    @classmethod
    def to_schema(cls) -> dict[str, object]:
        return cls.model_json_schema()


def original_evidence_key(reference: EvidenceReference) -> tuple[str, str, str, str]:
    """Return the immutable values used when deduplicating source evidence."""

    return (
        reference.snapshot_id,
        reference.snapshot_sha256,
        reference.json_pointer,
        reference.excerpt,
    )
