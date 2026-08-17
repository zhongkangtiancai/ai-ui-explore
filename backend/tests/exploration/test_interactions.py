"""Tests for bounded, non-mutating UI interaction discovery."""

from ai_ui_explorer.exploration.interactions import (
    ReadonlyInteractionCandidate,
    ReadonlyInteractionGate,
    extract_readonly_interaction_candidates,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.permission_comparison.models import (
    ElementEvidence,
    EvidenceReference,
    LocatorCandidateEvidence,
    PageEvidence,
)


def test_extracts_unique_tab_and_details_link_in_deterministic_order() -> None:
    candidates = extract_readonly_interaction_candidates(
        PageEvidence(
            page_key="https://app.example.test/dashboard",
            evidence_refs=[_evidence("page")],
            elements=[
                _element(
                    element_key="detail-link",
                    tag="a",
                    role="link",
                    accessible_name="查看详情",
                    href="https://app.example.test/details/1",
                ),
                _element(
                    element_key="overview-tab",
                    tag="button",
                    role="tab",
                    accessible_name="概览",
                    attributes={"aria-selected": "false"},
                ),
            ],
        )
    )

    assert [(item.kind, item.element_key) for item in candidates] == [
        ("switch_tab", "overview-tab"),
        ("view_details", "detail-link"),
    ]
    assert all(item.locator.uniqueness == "unique" for item in candidates)


def test_gate_rejects_dangerous_label_without_echoing_it() -> None:
    decision = ReadonlyInteractionGate().evaluate(
        _candidate(accessible_name="删除生产记录"),
        NavigationPolicy(allowed_origins=["https://app.example.test"]),
    )

    assert decision.allowed is False
    assert decision.reason_code == "dangerous_semantics"
    assert "删除生产记录" not in decision.safe_message


def test_gate_rejects_cross_origin_detail_target() -> None:
    decision = ReadonlyInteractionGate().evaluate(
        _candidate(target_url="https://outside.example.test/details/1"),
        NavigationPolicy(allowed_origins=["https://app.example.test"]),
    )

    assert decision.allowed is False
    assert decision.reason_code == "origin_not_allowed"


def _candidate(
    *,
    accessible_name: str = "查看详情",
    target_url: str = "https://app.example.test/details/1",
) -> ReadonlyInteractionCandidate:
    return ReadonlyInteractionCandidate(
        kind="view_details",
        element_key="detail-link",
        frame_path="main",
        locator=_locator(),
        target_summary=accessible_name,
        target_url=target_url,
    )


def _element(
    *,
    element_key: str,
    tag: str,
    role: str,
    accessible_name: str,
    attributes: dict[str, str] | None = None,
    href: str | None = None,
) -> ElementEvidence:
    return ElementEvidence(
        element_key=element_key,
        frame_path="main",
        tag=tag,
        role=role,
        accessible_name=accessible_name,
        attributes=attributes or {},
        href=href,
        locator_candidates=[_locator()],
        evidence_refs=[_evidence(element_key)],
    )


def _locator() -> LocatorCandidateEvidence:
    return LocatorCandidateEvidence(
        locator_id="locator-1",
        strategy="role",
        parameters={"role": "link", "name": "查看详情", "exact": True},
        source="observed",
        uniqueness="unique",
        stability="high",
        confidence=0.95,
        rank=1,
        recommended=True,
        frame_path="main",
        evidence_refs=[_evidence("locator")],
    )


def _evidence(suffix: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"evidence-{suffix}",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer="/frames/0",
        excerpt="safe evidence",
    )
