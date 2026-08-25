"""Bounded, redacted projections from successful Snapshot visits."""

from __future__ import annotations

from hashlib import sha256

from ai_ui_explorer.exploration.queue import ExplorationTarget
from ai_ui_explorer.exploration.runner import ExplorationRunResult
from ai_ui_explorer.knowledge.ids import canonical_json, stable_id
from ai_ui_explorer.permission_comparison.models import (
    BoundsEvidence,
    ElementEvidence,
    EvidenceReference,
    IdentityEvidenceBundle,
    IdentityRunState,
    LocatorCandidateEvidence,
    PageEvidence,
)
from ai_ui_explorer.snapshot.models import SnapshotDocument
from ai_ui_explorer.snapshot.redaction import Redactor

_MAX_ELEMENT_TEXT_CHARS = 500
_MAX_ATTRIBUTES = 32


class IdentityEvidenceCollector:
    """Collect one identity's safe evidence without retaining browser state."""

    def __init__(self, *, identity_id: str, redactor: Redactor | None = None) -> None:
        self._identity_id = identity_id
        self._redactor = redactor or Redactor()
        self._pages: list[PageEvidence] = []

    def record(self, target: ExplorationTarget, snapshot: SnapshotDocument) -> None:
        """Project a validated, already-redacted Snapshot into bounded evidence."""
        self._pages.append(project_snapshot(target, snapshot, self._redactor))

    def complete(self, _result: ExplorationRunResult) -> None:
        """Satisfy the Runner sink protocol without retaining run internals."""

    def bundle(self, *, state: IdentityRunState | str) -> IdentityEvidenceBundle:
        return IdentityEvidenceBundle(
            identity_id=self._identity_id,
            state=IdentityRunState(state),
            pages=self._pages,
        )


def project_snapshot(
    target: ExplorationTarget,
    snapshot: SnapshotDocument,
    redactor: Redactor,
) -> PageEvidence:
    """Project one Snapshot without retaining it or any browser state."""
    snapshot_sha256 = _snapshot_sha256(snapshot)
    return PageEvidence(
        page_key=redactor.redact_url(target.url).value,
        elements=_elements(snapshot, snapshot_sha256, redactor),
        evidence_refs=[
            _reference(
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                pointer="/source/final_url",
                excerpt=redactor.redact_url(snapshot.source.final_url).value,
            )
        ],
    )


def _elements(
    snapshot: SnapshotDocument,
    snapshot_sha256: str,
    redactor: Redactor,
) -> list[ElementEvidence]:
    locators_by_element: dict[
        tuple[str, str], list[LocatorCandidateEvidence]
    ] = {}
    for candidate_index, candidate in enumerate(snapshot.locator_candidates):
        locators_by_element.setdefault(
            (candidate.frame_ref, candidate.element_ref),
            [],
        ).append(
            _locator_candidate(
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                candidate_index=candidate_index,
                redactor=redactor,
            )
        )

    evidence: list[ElementEvidence] = []
    for frame_index, frame in enumerate(snapshot.frames):
        frame_path = _frame_path(snapshot, frame.frame_id)
        for element_index, element in enumerate(frame.elements):
            pointer = f"/frames/{frame_index}/elements/{element_index}"
            locator_candidates = locators_by_element.get(
                (frame.frame_id, element.element_id),
                [],
            )
            evidence.append(
                ElementEvidence(
                    element_key=f"{frame.frame_id}:{element.element_id}",
                    frame_path=frame_path,
                    tag=element.tag,
                    role=element.role,
                    accessible_name=_optional_text(
                        element.accessible_name,
                        redactor,
                    ),
                    text=_optional_text(element.text, redactor),
                    attributes=dict(
                        list(redactor.redact_mapping(element.attributes)[0].items())[
                            :_MAX_ATTRIBUTES
                        ]
                    ),
                    href=(
                        redactor.redact_url(element.href).value
                        if element.href is not None
                        else None
                    ),
                    visible=element.visible,
                    enabled=element.enabled,
                    bounds=(
                        BoundsEvidence(
                            x=element.bounds.x,
                            y=element.bounds.y,
                            width=element.bounds.width,
                            height=element.bounds.height,
                        )
                        if element.bounds is not None
                        else None
                    ),
                    locator_hints=[
                        candidate.locator_id for candidate in locator_candidates
                    ],
                    locator_candidates=locator_candidates,
                    evidence_refs=[
                        _reference(
                            snapshot=snapshot,
                            snapshot_sha256=snapshot_sha256,
                            pointer=pointer,
                            excerpt=_optional_text(
                                element.accessible_name,
                                redactor,
                            )
                            or element.tag,
                        )
                    ],
                )
            )
    return evidence


def _locator_candidate(
    *,
    snapshot: SnapshotDocument,
    snapshot_sha256: str,
    candidate_index: int,
    redactor: Redactor,
) -> LocatorCandidateEvidence:
    candidate = snapshot.locator_candidates[candidate_index]
    return LocatorCandidateEvidence(
        locator_id=candidate.locator_id,
        strategy=candidate.strategy,
        parameters={
            key: (
                redactor.redact_text(value).value
                if isinstance(value, str)
                else value
            )
            for key, value in candidate.parameters.items()
        },
        source=candidate.source,
        uniqueness=candidate.uniqueness,
        stability=candidate.stability,
        confidence=candidate.confidence,
        rank=candidate.rank,
        recommended=candidate.recommended,
        limitations=[
            redactor.redact_text(limitation).value
            for limitation in candidate.limitations
        ],
        frame_path=_frame_path(snapshot, candidate.frame_ref),
        evidence_refs=[
            _reference(
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                pointer=f"/locator_candidates/{candidate_index}",
                excerpt=candidate.locator_id,
            )
        ],
    )


def _snapshot_sha256(snapshot: SnapshotDocument) -> str:
    document = snapshot.model_dump(mode="json")
    return sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _optional_text(value: str | None, redactor: Redactor) -> str | None:
    if value is None:
        return None
    return redactor.redact_text(value).value[:_MAX_ELEMENT_TEXT_CHARS]


def _frame_path(snapshot: SnapshotDocument, frame_id: str) -> str:
    frames = {frame.frame_id: frame for frame in snapshot.frames}
    parts: list[str] = []
    current = frames[frame_id]
    while True:
        parts.append(current.frame_id)
        if current.parent_frame_id is None:
            break
        current = frames[current.parent_frame_id]
    return "/".join(reversed(parts))


def _reference(
    *,
    snapshot: SnapshotDocument,
    snapshot_sha256: str,
    pointer: str,
    excerpt: str,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=stable_id("evidence", snapshot_sha256, pointer),
        snapshot_id=str(snapshot.snapshot_id),
        snapshot_schema_version=snapshot.schema_version,
        snapshot_sha256=snapshot_sha256,
        json_pointer=pointer,
        excerpt=excerpt[:500],
    )
