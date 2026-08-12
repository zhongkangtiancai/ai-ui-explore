"""Tests for deterministic, evidence-based identity visibility comparisons."""

from ai_ui_explorer.permission_comparison.comparator import PermissionComparator
from ai_ui_explorer.permission_comparison.models import (
    ElementEvidence,
    EvidenceReference,
    IdentityEvidenceBundle,
    PageEvidence,
)


def _evidence(identity_id: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"evidence-{identity_id}",
        snapshot_id=f"snapshot-{identity_id}",
        snapshot_schema_version="1.1",
        snapshot_sha256=("a" if identity_id == "identity-1" else "b") * 64,
        json_pointer="/frames/0/elements/0",
        excerpt="safe evidence",
    )


def _page(
    path: str,
    *,
    identity_id: str,
    elements: list[ElementEvidence] | None = None,
) -> PageEvidence:
    return PageEvidence(
        page_key=f"https://app.example.test{path}",
        elements=elements or [],
        evidence_refs=[_evidence(identity_id)],
    )


def _bundle(
    identity_id: str,
    *,
    state: str = "completed",
    pages: list[PageEvidence],
) -> IdentityEvidenceBundle:
    return IdentityEvidenceBundle(
        identity_id=identity_id,
        state=state,
        pages=pages,
    )


def _element(
    identity_id: str,
    *,
    frame_path: str = "main",
    test_id: str | None = None,
) -> ElementEvidence:
    attributes = {"data-testid": test_id} if test_id is not None else {}
    return ElementEvidence(
        element_key=f"{frame_path}:element-{identity_id}",
        frame_path=frame_path,
        tag="a",
        role="link",
        accessible_name="Manage users",
        text="Manage users",
        attributes=attributes,
        href="https://app.example.test/admin/users",
        locator_hints=[],
        evidence_refs=[_evidence(identity_id)],
    )


def _difference(result: object, subject_key: str):
    return next(
        difference
        for difference in result.differences
        if difference.subject_key == subject_key
    )


def test_comparator_reports_admin_only_page_with_high_reliability() -> None:
    result = PermissionComparator().compare(
        [
            _bundle(
                "identity-1",
                pages=[
                    _page("/", identity_id="identity-1"),
                    _page("/admin", identity_id="identity-1"),
                ],
            ),
            _bundle(
                "identity-2",
                pages=[_page("/", identity_id="identity-2")],
            ),
        ]
    )

    difference = _difference(result, "page:https://app.example.test/admin")

    assert difference.kind == "observed_in_only_one_identity"
    assert difference.reliability == "high"


def test_comparator_marks_missing_page_inconclusive_after_partial_collection() -> None:
    result = PermissionComparator().compare(
        [
            _bundle(
                "identity-1",
                pages=[_page("/admin", identity_id="identity-1")],
            ),
            _bundle("identity-2", state="partial", pages=[]),
        ]
    )

    difference = _difference(result, "page:https://app.example.test/admin")

    assert difference.reliability == "inconclusive"
    assert difference.identity_states["identity-2"] == "collection_incomplete"


def test_comparator_refuses_to_match_same_test_id_in_different_frames() -> None:
    result = PermissionComparator().compare(
        [
            _bundle(
                "identity-1",
                pages=[
                    _page(
                        "/",
                        identity_id="identity-1",
                        elements=[_element("identity-1", frame_path="main", test_id="users")],
                    )
                ],
            ),
            _bundle(
                "identity-2",
                pages=[
                    _page(
                        "/",
                        identity_id="identity-2",
                        elements=[_element("identity-2", frame_path="main/child", test_id="users")],
                    )
                ],
            ),
        ]
    )

    assert all(difference.kind != "safe_attribute_changed" for difference in result.differences)
    assert all(difference.kind != "link_target_changed" for difference in result.differences)


def test_comparator_treats_root_index_document_as_the_root_page() -> None:
    result = PermissionComparator().compare(
        [
            _bundle("identity-1", pages=[_page("/", identity_id="identity-1")]),
            _bundle(
                "identity-2",
                pages=[_page("/index.html", identity_id="identity-2")],
            ),
        ]
    )

    assert result.differences == []


def test_comparator_uses_link_target_to_disambiguate_same_role_and_name() -> None:
    first = _element("identity-1", test_id=None)
    second = first.model_copy(
        update={
            "element_key": "main:second",
            "href": "https://app.example.test/settings",
        }
    )
    result = PermissionComparator().compare(
        [
            _bundle(
                "identity-1",
                pages=[_page("/", identity_id="identity-1", elements=[first, second])],
            ),
            _bundle(
                "identity-2",
                pages=[_page("/", identity_id="identity-2", elements=[first])],
            ),
        ]
    )

    assert len(result.differences) == 1
    assert result.differences[0].reliability == "high"
    assert "href:https://app.example.test/settings" in result.differences[0].subject_key
