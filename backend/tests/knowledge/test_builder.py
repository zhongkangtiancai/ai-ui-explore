"""End-to-end tests for deterministic Snapshot-to-knowledge mapping."""

import traceback
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_ui_explorer.knowledge.builder import (
    KnowledgeBuildError,
    KnowledgePackageBuilder,
)
from ai_ui_explorer.knowledge.ids import resolve_json_pointer
from ai_ui_explorer.knowledge.models import KnowledgeLimits
from ai_ui_explorer.knowledge.predicates import Predicate
from ai_ui_explorer.snapshot.models import SnapshotError
from tests.knowledge.factories import make_manifest
from tests.snapshot.factories import (
    make_element,
    make_frame,
    make_legacy_snapshot,
    make_locator_candidate,
    make_snapshot,
)

_OCCURRED_AT = datetime(2026, 7, 29, 0, 0, 0, tzinfo=UTC)


def test_builder_maps_entities_facts_evidence_and_locators() -> None:
    snapshot = _snapshot_with_nested_frames_and_locators()

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert package.status == "completed"
    assert package.application.application_id == "example-app"
    assert [entity.entity_type for entity in package.entities] == [
        "element",
        "element",
        "frame",
        "frame",
        "page",
    ]
    assert package.inferences == []
    assert package.exploration_run.content_status == "insufficient_evidence"
    assert package.exploration_run.identity_context.status == "not_provided"
    assert package.exploration_run.access_status == "public"
    exploration_predicates = {
        fact.predicate
        for fact in package.facts
        if fact.subject_ref == package.exploration_run.exploration_run_id
    }
    assert exploration_predicates == {
        Predicate.EXPLORATION_SOURCE_SNAPSHOT,
        Predicate.EXPLORATION_COLLECTION_STATUS,
    }

    evidence_ids = {item.evidence_id for item in package.evidence}
    assert all(
        set(entity.source_refs) <= evidence_ids for entity in package.entities
    )
    assert all(fact.evidence_refs for fact in package.facts)
    assert all(
        set(fact.evidence_refs) <= evidence_ids for fact in package.facts
    )
    for evidence in package.evidence:
        resolve_json_pointer(
            snapshot.model_dump(mode="json"),
            evidence.json_pointer,
        )

    entity_ids = {entity.entity_id for entity in package.entities}
    relationship_facts = [
        fact for fact in package.facts if fact.object_ref is not None
    ]
    assert {
        fact.predicate for fact in relationship_facts
    } >= {
        Predicate.FRAME_PARENT,
        Predicate.ELEMENT_LOCATED_IN,
        Predicate.LOCATOR_LOCATES,
    }
    assert all(fact.object_ref in entity_ids for fact in relationship_facts)
    assert all(isinstance(fact.predicate, Predicate) for fact in package.facts)

    assert [
        (locator.strategy, locator.rank)
        for locator in package.locator_candidates
    ] == [
        ("role", 1),
        ("testid", 2),
        ("label", 1),
    ]
    assert [
        (
            locator.uniqueness,
            locator.stability,
            locator.recommended,
            locator.match_count,
        )
        for locator in package.locator_candidates
    ] == [
        ("unique", "high", True, 1),
        ("multiple", "medium", False, 2),
        ("unique", "high", True, 1),
    ]
    locator_evidence = {item.evidence_id: item for item in package.evidence}
    current_locator_ids = {
        item.locator_id for item in package.locator_candidates
    }
    locator_facts = [
        fact
        for fact in package.facts
        if fact.subject_ref in current_locator_ids
    ]
    assert {
        fact.predicate for fact in locator_facts
    } == {
        Predicate.LOCATOR_LOCATES,
        Predicate.LOCATOR_STRATEGY,
        Predicate.LOCATOR_UNIQUENESS,
        Predicate.LOCATOR_STABILITY,
        Predicate.LOCATOR_RECOMMENDED,
    }
    for fact in locator_facts:
        pointer = locator_evidence[fact.evidence_refs[0]].json_pointer
        source_value = resolve_json_pointer(
            snapshot.model_dump(mode="json"), pointer
        )
        assert pointer.startswith("/locator_candidates/")
        if fact.predicate == Predicate.LOCATOR_LOCATES:
            assert isinstance(source_value, str)
        else:
            assert source_value == fact.value


def test_builder_emits_only_supported_entities_and_explicit_future_gaps() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_snapshot(),
    )

    assert {entity.entity_type for entity in package.entities} == {
        "page",
        "frame",
        "element",
    }
    unsupported_aspects = {
        gap.aspect
        for gap in package.knowledge_gaps
        if gap.reason_code == "unsupported_in_current_sprint"
    }
    assert unsupported_aspects == {
        "entity.module",
        "entity.action",
        "entity.workflow",
        "entity.permission",
        "entity.data_scope",
        "entity.change_history",
    }
    assert any(
        gap.reason_code == "identity_not_available"
        for gap in package.knowledge_gaps
    )


def test_builder_maps_legacy_hints_and_bounds_without_inventing_selectors() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_legacy_snapshot(),
    )

    assert [locator.strategy for locator in package.locator_candidates] == [
        "role",
        "position",
    ]
    assert all(
        locator.uniqueness == "unverified"
        and locator.match_count is None
        and locator.recommended is False
        for locator in package.locator_candidates
    )
    assert not {
        "css",
        "xpath",
    } & {locator.strategy for locator in package.locator_candidates}
    assert any(
        gap.reason_code == "snapshot_version_limited"
        for gap in package.knowledge_gaps
    )


def test_builder_marks_incomplete_source_partial_with_truncation_semantics() -> None:
    source_error = SnapshotError(
        scope="output",
        error_code="output_size_limit",
        message="Snapshot was compacted.",
        recoverable=True,
        occurred_at=_OCCURRED_AT,
    )
    snapshot = make_snapshot(
        status="partial",
        errors=[source_error],
        truncated=True,
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert package.status == "partial"
    assert package.exploration_run.collection_status == "partial"
    assert package.exploration_run.exploration_status == "partial"
    assert package.stop_reasons
    assert any(
        gap.reason_code == "collection_truncated"
        for gap in package.knowledge_gaps
    )


def test_authentication_origin_without_access_evidence_stays_unknown() -> None:
    snapshot = make_snapshot(
        source={
            "requested_url": "https://example.test/private",
            "final_url": "https://sso.example.test/login",
            "title": "Sign in",
        },
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert package.exploration_run.access_status == "unknown"
    assert package.entities == []
    assert package.locator_candidates == []
    assert not any(
        fact.predicate.value.startswith(("page.", "frame.", "element."))
        for fact in package.facts
    )
    assert {item.json_pointer for item in package.evidence} == {
        "/snapshot_id",
        "/status",
    }


@pytest.mark.parametrize(
    "final_url",
    [
        "https://sso.example.test/login",
        "https://outside.example.test/landing",
    ],
)
def test_non_target_final_page_never_creates_target_content_knowledge(
    final_url: str,
) -> None:
    base_snapshot = _snapshot_with_nested_frames_and_locators()
    snapshot = type(base_snapshot).model_validate(
        {
            **base_snapshot.model_dump(mode="json"),
            "source": {
                "requested_url": "https://example.test/private",
                "final_url": final_url,
                "title": "External result",
            },
        }
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert package.entities == []
    assert package.locator_candidates == []
    assert all(
        not item.json_pointer.startswith(("/page", "/frames", "/source"))
        for item in package.evidence
    )
    assert all(
        not fact.predicate.value.startswith(("page.", "frame.", "element."))
        for fact in package.facts
    )


@pytest.mark.parametrize(
    ("error_code", "final_url", "expected_status"),
    [
        (
            "authentication_required",
            "https://sso.example.test/login",
            "authentication_required",
        ),
        (
            "permission_denied",
            "https://example.test/private",
            "permission_denied",
        ),
        (
            "anti_automation_blocked",
            "https://example.test/private",
            "anti_automation_blocked",
        ),
        (
            "rate_limited",
            "https://example.test/private",
            "rate_limited",
        ),
    ],
)
def test_builder_maps_only_controlled_access_errors_to_observations(
    error_code: str,
    final_url: str,
    expected_status: str,
) -> None:
    source_error = SnapshotError(
        scope="page",
        error_code=error_code,
        message="Controlled access signal.",
        recoverable=True,
        occurred_at=_OCCURRED_AT,
    )
    snapshot = make_snapshot(
        status="partial",
        source={
            "requested_url": "https://example.test/private",
            "final_url": final_url,
            "title": "Access result",
        },
        errors=[source_error],
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert package.exploration_run.access_status == expected_status
    assert len(package.observations) == 1
    assert package.observations[0].evidence_refs


def test_builder_does_not_promote_unknown_errors_or_missing_values() -> None:
    source_error = SnapshotError(
        scope="page",
        error_code="login_text_seen",
        message="The page happened to contain the word login.",
        recoverable=True,
        occurred_at=_OCCURRED_AT,
    )
    element = make_element(
        role=None,
        accessible_name=None,
        text=None,
        enabled=None,
        checked=None,
        selected=None,
        expanded=None,
    )
    frame = make_frame(elements=[element])
    snapshot = make_snapshot(
        status="partial",
        frames=[frame],
        errors=[source_error],
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert package.exploration_run.access_status == "unknown"
    assert package.observations == []
    element_entity = next(
        entity
        for entity in package.entities
        if entity.entity_type == "element"
    )
    element_predicates = {
        fact.predicate
        for fact in package.facts
        if fact.subject_ref == element_entity.entity_id
    }
    assert not {
        Predicate.ELEMENT_ROLE,
        Predicate.ELEMENT_ACCESSIBLE_NAME,
        Predicate.ELEMENT_TEXT,
        Predicate.ELEMENT_ENABLED,
        Predicate.ELEMENT_CHECKED,
        Predicate.ELEMENT_SELECTED,
        Predicate.ELEMENT_EXPANDED,
    } & element_predicates


def test_builder_skips_blank_text_facts_but_preserves_false_and_zero() -> None:
    element = make_element(
        tag=" ",
        role="",
        accessible_name="  ",
        text="",
        visible=False,
    )
    frame = make_frame(name=" ", depth=0, elements=[element])
    snapshot = make_snapshot(
        source={
            "requested_url": "https://example.test/",
            "final_url": "https://example.test/",
            "title": " ",
        },
        page={
            "main_frame_id": "main",
            "viewport_width": 1280,
            "viewport_height": 720,
            "language": " ",
        },
        frames=[frame],
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    values_by_predicate = {
        fact.predicate: fact.value for fact in package.facts if fact.value is not None
    }
    assert Predicate.PAGE_TITLE not in values_by_predicate
    assert Predicate.PAGE_LANGUAGE not in values_by_predicate
    assert Predicate.FRAME_NAME not in values_by_predicate
    assert not {
        Predicate.ELEMENT_TAG,
        Predicate.ELEMENT_ROLE,
        Predicate.ELEMENT_ACCESSIBLE_NAME,
        Predicate.ELEMENT_TEXT,
    } & set(values_by_predicate)
    assert values_by_predicate[Predicate.ELEMENT_VISIBLE] is False
    assert values_by_predicate[Predicate.FRAME_DEPTH] == 0


def test_builder_rejects_duplicate_element_ids_within_one_frame() -> None:
    first = make_element(element_id="duplicate", traversal_index=0)
    second = make_element(element_id="duplicate", traversal_index=1)
    snapshot = make_snapshot(
        frames=[make_frame(elements=[first, second])],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": 2,
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "locator_candidate_count": 0,
            "duration_ms": 1,
        },
    )

    with pytest.raises(
        KnowledgeBuildError,
        match=r"^Knowledge package could not be built\.$",
    ):
        KnowledgePackageBuilder().build(
            manifest=make_manifest(),
            snapshot=snapshot,
        )


def test_builder_keeps_cross_frame_duplicate_element_ids_separate() -> None:
    root = make_frame(
        frame_id="root",
        elements=[
            make_element(
                element_id="same",
                frame_id="root",
                accessible_name="Root element",
            )
        ],
    )
    child = make_frame(
        frame_id="child",
        parent_frame_id="root",
        traversal_index=1,
        depth=1,
        elements=[
            make_element(
                element_id="same",
                frame_id="child",
                accessible_name="Child element",
            )
        ],
    )
    locator = make_locator_candidate(
        locator_id="child-same",
        element_ref="same",
        frame_ref="child",
        rank=1,
    )
    snapshot = make_snapshot(
        frames=[root, child],
        page={
            "main_frame_id": "root",
            "viewport_width": 1280,
            "viewport_height": 720,
            "language": "en",
        },
        locator_candidates=[locator],
        statistics={
            "frame_count": 2,
            "completed_frame_count": 2,
            "failed_frame_count": 0,
            "element_count": 2,
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "locator_candidate_count": 1,
            "duration_ms": 1,
        },
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    evidence_by_id = {item.evidence_id: item for item in package.evidence}
    names = {
        resolve_json_pointer(
            snapshot.model_dump(mode="json"),
            evidence_by_id[fact.evidence_refs[0]].json_pointer,
        )
        for fact in package.facts
        if fact.predicate == Predicate.ELEMENT_ACCESSIBLE_NAME
    }
    assert names == {"Root element", "Child element"}
    assert package.locator_candidates[0].element_ref in {
        fact.subject_ref
        for fact in package.facts
        if fact.predicate == Predicate.ELEMENT_ACCESSIBLE_NAME
    }


def test_builder_maps_repeated_current_locator_semantics_one_to_one() -> None:
    first = make_locator_candidate(
        locator_id="role-first",
        element_ref="element-0",
        frame_ref="main",
        rank=1,
    )
    second = make_locator_candidate(
        locator_id="role-second",
        element_ref="element-0",
        frame_ref="main",
        rank=2,
    )
    snapshot = make_snapshot(
        locator_candidates=[first, second],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": 1,
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "locator_candidate_count": 2,
            "duration_ms": 1,
        },
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert len(package.locator_candidates) == 2
    assert len({item.locator_id for item in package.locator_candidates}) == 2
    assert [item.rank for item in package.locator_candidates] == [1, 2]


def test_snapshot_rejects_empty_current_locator_parameters() -> None:
    with pytest.raises(ValidationError):
        make_locator_candidate(
            locator_id="empty-parameters",
            element_ref="element-0",
            frame_ref="main",
            parameters={},
        )


def test_builder_uses_narrow_source_evidence_for_content_entities() -> None:
    snapshot = _snapshot_with_nested_frames_and_locators()

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    evidence_by_id = {item.evidence_id: item for item in package.evidence}
    source_pointers = [
        (
            entity.entity_type,
            [
                evidence_by_id[source_ref].json_pointer
                for source_ref in entity.source_refs
            ],
        )
        for entity in package.entities
    ]
    assert [
        pointers
        for entity_type, pointers in source_pointers
        if entity_type == "page"
    ] == [["/page/main_frame_id"]]
    assert all(
        pointer.endswith("/frame_id")
        for entity_type, pointers in source_pointers
        if entity_type == "frame"
        for pointer in pointers
    )
    assert all(
        pointer.endswith("/element_id")
        for entity_type, pointers in source_pointers
        if entity_type == "element"
        for pointer in pointers
    )


def test_builder_does_not_emit_legacy_inferred_locator_metadata_facts() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_legacy_snapshot(),
    )

    locator_subjects = {
        locator.locator_id for locator in package.locator_candidates
    }
    metadata_predicates = {
        Predicate.LOCATOR_UNIQUENESS,
        Predicate.LOCATOR_STABILITY,
        Predicate.LOCATOR_RECOMMENDED,
    }
    assert not [
        fact
        for fact in package.facts
        if fact.subject_ref in locator_subjects
        and fact.predicate in metadata_predicates
    ]


def test_builder_repeats_identical_model_output_and_structured_hints() -> None:
    snapshot = _snapshot_with_nested_frames_and_locators()
    builder = KnowledgePackageBuilder()

    first = builder.build(manifest=make_manifest(), snapshot=snapshot)
    second = builder.build(manifest=make_manifest(), snapshot=snapshot)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    frame_hints = [
        hint.value
        for entity in first.entities
        if entity.entity_type == "frame"
        for hint in entity.match_hints
        if hint.hint_type == "frame_ancestry"
    ]
    assert frame_hints == ['["root","child"]', '["root"]']
    locator_hints = [
        hint.value
        for entity in first.entities
        if entity.entity_type == "element"
        for hint in entity.match_hints
        if hint.hint_type == "locator_parameter"
    ]
    assert (
        '{"parameters":{"exact":true,"name":"Submit","role":"button"},'
        '"strategy":"role"}'
    ) in locator_hints


def test_package_id_changes_when_manifest_content_changes() -> None:
    snapshot = make_snapshot()

    first = KnowledgePackageBuilder().build(
        manifest=make_manifest(name="Application A"),
        snapshot=snapshot,
    )
    second = KnowledgePackageBuilder().build(
        manifest=make_manifest(name="Application B"),
        snapshot=snapshot,
    )

    assert first.package_id != second.package_id


def test_builder_redacts_all_persisted_source_derived_values() -> None:
    secret = "synthetic-secret-token"
    source_error = SnapshotError(
        scope="page",
        error_code="permission_denied",
        message=f"authorization: Bearer {secret}",
        recoverable=True,
        occurred_at=_OCCURRED_AT,
    )
    element = make_element(
        accessible_name=f"token={secret}",
        text=f"authorization: Bearer {secret}",
        attributes={"data-testid": f"token={secret}"},
    )
    frame = make_frame(
        elements=[element],
        url=f"https://example.test/private?token={secret}",
    )
    snapshot = make_snapshot(
        status="partial",
        source={
            "requested_url": f"https://example.test/private?token={secret}",
            "final_url": f"https://example.test/private?token={secret}",
            "title": f"token={secret}",
        },
        frames=[frame],
        errors=[source_error],
    )

    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
    )

    assert secret not in package.model_dump_json()


def test_builder_rejects_outside_request_with_fixed_safe_error() -> None:
    secret = "synthetic-secret-token"
    snapshot = make_snapshot(
        source={
            "requested_url": f"https://outside.invalid/?token={secret}",
            "final_url": f"https://outside.invalid/?token={secret}",
            "title": secret,
        },
    )

    with pytest.raises(
        KnowledgeBuildError,
        match=r"^Snapshot request origin is not allowed\.$",
    ) as captured:
        KnowledgePackageBuilder().build(
            manifest=make_manifest(),
            snapshot=snapshot,
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in _exception_surface(captured.value)
    assert "outside.invalid" not in _exception_surface(captured.value)


def test_builder_reserves_truncation_gap_when_gap_budget_is_one() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_snapshot(),
        limits=KnowledgeLimits(max_knowledge_gaps=1),
    )

    assert package.status == "partial"
    assert package.stop_reasons == ["knowledge_gap_limit"]
    assert len(package.knowledge_gaps) == 1
    assert package.knowledge_gaps[0].reason_code == "collection_truncated"


def test_builder_budgeted_evidence_is_exact_reference_closure() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_snapshot(),
        limits=KnowledgeLimits(
            max_facts=1,
            max_locators_per_element=1,
            max_observations=0,
            max_knowledge_gaps=2,
        ),
    )

    referenced_evidence = {
        evidence_ref
        for collection in (
            package.entities,
            package.locator_candidates,
            package.facts,
            package.observations,
            package.knowledge_gaps,
        )
        for item in collection
        for evidence_ref in getattr(
            item,
            "source_refs",
            getattr(item, "evidence_refs", []),
        )
    }

    assert {evidence.evidence_id for evidence in package.evidence} == referenced_evidence
    assert package.statistics.evidence_count == len(referenced_evidence)


def _snapshot_with_nested_frames_and_locators():
    root_element = make_element(
        element_id="root-submit",
        frame_id="root",
        traversal_index=0,
        attributes={"data-testid": "submit-action", "type": "submit"},
    )
    child_element = make_element(
        element_id="child-submit",
        frame_id="child",
        traversal_index=0,
    )
    root_frame = make_frame(
        frame_id="root",
        traversal_index=0,
        name="root",
        elements=[root_element],
    )
    child_frame = make_frame(
        frame_id="child",
        parent_frame_id="root",
        traversal_index=1,
        depth=1,
        name="child",
        elements=[child_element],
    )
    locators = [
        make_locator_candidate(
            locator_id="child-label",
            element_ref="child-submit",
            frame_ref="child",
            strategy="label",
            parameters={"value": "Submit", "exact": True},
            rank=1,
        ),
        make_locator_candidate(
            locator_id="root-testid",
            element_ref="root-submit",
            frame_ref="root",
            strategy="testid",
            parameters={"value": "submit-action"},
            uniqueness="multiple",
            match_count=2,
            stability="medium",
            confidence=0.7,
            rank=2,
            recommended=False,
        ),
        make_locator_candidate(
            locator_id="root-role",
            element_ref="root-submit",
            frame_ref="root",
            rank=1,
        ),
    ]
    return make_snapshot(
        frames=[child_frame, root_frame],
        page={
            "main_frame_id": "root",
            "viewport_width": 1280,
            "viewport_height": 720,
            "language": "en",
        },
        locator_candidates=locators,
        statistics={
            "frame_count": 2,
            "completed_frame_count": 2,
            "failed_frame_count": 0,
            "element_count": 2,
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "locator_candidate_count": 3,
            "duration_ms": 1,
        },
    )


def _exception_surface(error: BaseException) -> str:
    pending = [error]
    seen: set[int] = set()
    parts: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        parts.extend((str(current), repr(current)))
        parts.extend(
            traceback.TracebackException.from_exception(current).format()
        )
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(parts)
