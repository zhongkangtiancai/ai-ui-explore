"""Deterministic, conservative comparison of identity evidence bundles."""

from ai_ui_explorer.knowledge.ids import stable_id
from ai_ui_explorer.permission_comparison.models import (
    DifferenceKind,
    DifferenceReliability,
    ElementEvidence,
    IdentityEvidenceBundle,
    IdentityRunState,
    ObservationState,
    PageEvidence,
    PermissionComparisonResult,
    VisibilityDifference,
)


class PermissionComparator:
    """Compare only observations that have deterministic, stable keys."""

    def compare(
        self,
        bundles: list[IdentityEvidenceBundle],
    ) -> PermissionComparisonResult:
        ordered_bundles = sorted(bundles, key=lambda bundle: bundle.identity_id)
        pages_by_identity = {
            bundle.identity_id: {
                canonical_page_key(page.page_key): page for page in bundle.pages
            }
            for bundle in ordered_bundles
        }
        page_keys = sorted(
            {
                page_key
                for pages in pages_by_identity.values()
                for page_key in pages
            }
        )
        differences: list[VisibilityDifference] = []
        for page_key in page_keys:
            page_difference = _page_difference(
                page_key,
                ordered_bundles,
                pages_by_identity,
            )
            if page_difference is not None:
                differences.append(page_difference)
            differences.extend(
                _element_differences(
                    page_key,
                    ordered_bundles,
                    pages_by_identity,
                )
            )

        if any(bundle.state != IdentityRunState.COMPLETED for bundle in ordered_bundles):
            differences = [
                difference.model_copy(
                    update={
                        "reliability": DifferenceReliability.INCONCLUSIVE,
                        "reason_codes": sorted(
                            set(difference.reason_codes)
                            | {"collection_incomplete"}
                        ),
                    }
                )
                for difference in differences
            ]

        return PermissionComparisonResult(
            comparison_id="comparison-1",
            status=(
                "completed"
                if all(bundle.state == IdentityRunState.COMPLETED for bundle in bundles)
                else "partial"
            ),
            identities=ordered_bundles,
            differences=sorted(
                differences,
                key=lambda difference: difference.difference_id,
            ),
        )


def canonical_page_key(url: str) -> str:
    """Retain the observed URL because route aliases are application-specific."""
    return url


def element_match_key(
    page: PageEvidence,
    element: ElementEvidence,
) -> str | None:
    """Return a unique stable key scoped to one page and Frame, if available."""
    element_keys = _element_candidate_keys(page)
    return element_keys.get(element.element_key)


def _page_difference(
    page_key: str,
    bundles: list[IdentityEvidenceBundle],
    pages_by_identity: dict[str, dict[str, PageEvidence]],
) -> VisibilityDifference | None:
    states = {
        bundle.identity_id: _observation_state(
            bundle,
            page_key in pages_by_identity[bundle.identity_id],
        )
        for bundle in bundles
    }
    if set(states.values()) == {ObservationState.OBSERVED}:
        return None
    evidence_refs = [
        reference
        for bundle in bundles
        for reference in (
            pages_by_identity[bundle.identity_id][page_key].evidence_refs
            if page_key in pages_by_identity[bundle.identity_id]
            else []
        )
    ]
    return VisibilityDifference(
        difference_id=stable_id(
            "difference",
            "page",
            page_key,
            _stable_states(states),
        ),
        kind=DifferenceKind.OBSERVED_IN_ONLY_ONE_IDENTITY,
        subject_key=f"page:{page_key}",
        identity_states=states,
        evidence_refs=evidence_refs,
        reason_codes=_reason_codes(states),
        reliability=_reliability(states),
    )


def _element_differences(
    page_key: str,
    bundles: list[IdentityEvidenceBundle],
    pages_by_identity: dict[str, dict[str, PageEvidence]],
) -> list[VisibilityDifference]:
    keys_by_identity = {
        bundle.identity_id: _element_candidate_keys(
            pages_by_identity[bundle.identity_id][page_key]
        )
        if page_key in pages_by_identity[bundle.identity_id]
        else {}
        for bundle in bundles
    }
    keys = sorted({key for values in keys_by_identity.values() for key in values.values()})
    differences: list[VisibilityDifference] = []
    for match_key in keys:
        elements = {
            bundle.identity_id: _element_for_match_key(
                pages_by_identity[bundle.identity_id].get(page_key),
                match_key,
            )
            for bundle in bundles
        }
        states = {
            bundle.identity_id: _observation_state(
                bundle,
                elements[bundle.identity_id] is not None,
            )
            for bundle in bundles
        }
        observed = [element for element in elements.values() if element is not None]
        if any(state != ObservationState.OBSERVED for state in states.values()):
            differences.append(
                VisibilityDifference(
                    difference_id=stable_id(
                        "difference",
                        "element",
                        page_key,
                        match_key,
                        _stable_states(states),
                    ),
                    kind=DifferenceKind.OBSERVED_IN_ONLY_ONE_IDENTITY,
                    subject_key=f"element:{page_key}:{match_key}",
                    identity_states=states,
                    evidence_refs=[
                        reference
                        for element in observed
                        for reference in element.evidence_refs
                    ],
                    reason_codes=_reason_codes(states),
                    reliability=_reliability(states),
                )
            )
            continue
        if len({element.href for element in observed}) > 1:
            differences.append(
                VisibilityDifference(
                    difference_id=stable_id("difference", "href", page_key, match_key),
                    kind=DifferenceKind.LINK_TARGET_CHANGED,
                    subject_key=f"element:{page_key}:{match_key}",
                    identity_states=states,
                    evidence_refs=[
                        reference
                        for element in observed
                        for reference in element.evidence_refs
                    ],
                    reliability=DifferenceReliability.HIGH,
                )
            )
    return differences


def _element_candidate_keys(page: PageEvidence) -> dict[str, str]:
    candidates: dict[str, list[tuple[str, str]]] = {}
    for element in page.elements:
        candidate = _candidate_key(element)
        if candidate is not None:
            candidates.setdefault(candidate, []).append((element.element_key, candidate))
    return {
        element_key: candidate
        for candidate, matches in candidates.items()
        if len(matches) == 1
        for element_key, candidate in matches
    }


def _candidate_key(element: ElementEvidence) -> str | None:
    frame_prefix = f"{element.frame_path}\u0000"
    test_id = element.attributes.get("data-testid")
    if test_id:
        return f"{frame_prefix}testid:{test_id}"
    element_id = element.attributes.get("id")
    if element_id:
        return f"{frame_prefix}id:{element_id}"
    if element.href and element.role and element.accessible_name:
        return (
            f"{frame_prefix}href:{element.href}\u0000{element.role}"
            f"\u0000{element.accessible_name}"
        )
    if element.role and element.accessible_name:
        return f"{frame_prefix}role:{element.role}\u0000{element.accessible_name}"
    return None


def _element_for_match_key(
    page: PageEvidence | None,
    match_key: str,
) -> ElementEvidence | None:
    if page is None:
        return None
    keys = _element_candidate_keys(page)
    for element in page.elements:
        if keys.get(element.element_key) == match_key:
            return element
    return None


def _observation_state(
    bundle: IdentityEvidenceBundle,
    observed: bool,
) -> ObservationState:
    if observed:
        return ObservationState.OBSERVED
    if bundle.state == IdentityRunState.COMPLETED:
        return ObservationState.NOT_OBSERVED
    if bundle.state == IdentityRunState.PARTIAL:
        return ObservationState.COLLECTION_INCOMPLETE
    if bundle.state == IdentityRunState.FAILED:
        return ObservationState.COLLECTION_FAILED
    return ObservationState.AUTHENTICATION_UNVERIFIED


def _reason_codes(states: dict[str, ObservationState]) -> list[str]:
    codes = {
        "collection_truncated"
        if state == ObservationState.COLLECTION_INCOMPLETE
        else "collection_failed"
        if state == ObservationState.COLLECTION_FAILED
        else "authentication_unverified"
        for state in states.values()
        if state
        in {
            ObservationState.COLLECTION_INCOMPLETE,
            ObservationState.COLLECTION_FAILED,
            ObservationState.AUTHENTICATION_UNVERIFIED,
        }
    }
    return sorted(codes)


def _reliability(
    states: dict[str, ObservationState],
) -> DifferenceReliability:
    complete_states = {
        ObservationState.OBSERVED,
        ObservationState.NOT_OBSERVED,
    }
    if any(state not in complete_states for state in states.values()):
        return DifferenceReliability.INCONCLUSIVE
    return DifferenceReliability.HIGH


def _stable_states(states: dict[str, ObservationState]) -> dict[str, str]:
    return {
        identity_id: state.value
        for identity_id, state in sorted(states.items())
    }
