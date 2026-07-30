"""Tests for the strict Sprint 2 knowledge package contract."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError

from ai_ui_explorer.knowledge.models import (
    Evidence,
    ExplorationRun,
    Fact,
    IdentityContext,
    Inference,
    KnowledgeApplication,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeLimits,
    KnowledgeLocator,
    KnowledgePackage,
    KnowledgeStatistics,
    MatchHint,
    Observation,
)
from ai_ui_explorer.knowledge.predicates import Predicate

from .factories import (
    OBSERVED_FROM,
    make_entity,
    make_evidence,
    make_exploration_run,
    make_fact,
    make_gap,
    make_locator,
    make_package,
)

_MODEL_TYPES: tuple[type[BaseModel], ...] = (
    MatchHint,
    KnowledgeLimits,
    KnowledgeApplication,
    IdentityContext,
    ExplorationRun,
    KnowledgeEntity,
    KnowledgeLocator,
    Evidence,
    Fact,
    Observation,
    Inference,
    KnowledgeGap,
    KnowledgeStatistics,
    KnowledgePackage,
)


def test_every_knowledge_model_is_frozen_and_forbids_extra_fields() -> None:
    for model_type in _MODEL_TYPES:
        assert model_type.model_config.get("frozen") is True
        assert model_type.model_config.get("extra") == "forbid"

    package = make_package()
    for model in (
        package,
        package.limits,
        package.application,
        package.exploration_run,
        package.exploration_run.identity_context,
        *package.entities,
        *package.entities[0].match_hints,
        *package.locator_candidates,
        *package.evidence,
        *package.facts,
        package.statistics,
    ):
        with pytest.raises(ValidationError):
            model.__class__.model_validate(
                {**model.model_dump(mode="python"), "unexpected": True}
            )


def test_nested_knowledge_containers_are_deeply_immutable() -> None:
    package = make_package()

    with pytest.raises(TypeError):
        package.entities.clear()
    with pytest.raises(TypeError):
        package.locator_candidates[0].parameters["role"] = "link"
    with pytest.raises(TypeError):
        package.locator_candidates[0].parameters.clear()
    with pytest.raises(TypeError):
        package.stop_reasons.append("mutated-after-validation")
    with pytest.raises(TypeError):
        package.application.allowed_origins.append(
            "https://other.example.test"
        )


def test_deeply_immutable_models_dump_copy_and_describe_public_shapes() -> None:
    package = make_package()

    dumped = package.model_dump(mode="python")
    assert isinstance(dumped["entities"], list)
    assert isinstance(dumped["locator_candidates"][0]["parameters"], dict)
    assert KnowledgePackage.model_validate(dumped) == package

    copied = package.model_copy()
    assert copied == package
    with pytest.raises(TypeError):
        copied.entities.clear()

    partial_values = package.model_dump(mode="python")
    partial_gap = make_gap(
        gap_id="gap-truncated",
        reason_code="collection_truncated",
    )
    partial = package.model_copy(
        update={
            "status": "partial",
            "stop_reasons": ["conversion_truncated"],
            "knowledge_gaps": [partial_gap],
            "statistics": {
                **partial_values["statistics"],
                "knowledge_gap_count": 1,
            },
        }
    )
    assert partial.status == "partial"
    with pytest.raises(TypeError):
        partial.stop_reasons.append("late-mutation")

    schema = KnowledgePackage.to_schema()
    assert schema["properties"]["entities"]["type"] == "array"
    locator_definition = schema["$defs"]["KnowledgeLocator"]
    assert locator_definition["properties"]["parameters"]["type"] == "object"


@pytest.mark.parametrize(
    ("value", "object_ref"),
    [
        (None, None),
        ("button", "element-other"),
    ],
)
def test_fact_requires_exactly_one_value_or_object_ref(
    value: str | None,
    object_ref: str | None,
) -> None:
    with pytest.raises(ValidationError):
        make_fact(value=value, object_ref=object_ref)


def test_observed_fact_requires_confidence_one_and_utc_timestamp() -> None:
    with pytest.raises(ValidationError):
        make_fact(confidence=0.99)
    with pytest.raises(ValidationError):
        make_fact(observed_at=datetime(2026, 7, 30))
    with pytest.raises(ValidationError):
        make_fact(
            observed_at=datetime(
                2026,
                7,
                30,
                tzinfo=timezone_with_offset(hours=8),
            )
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"evidence_refs": []},
        {"confidence": 0.0},
        {"confidence": 1.0},
        {"limitations": []},
        {"promotion_status": "verified"},
    ],
)
def test_observation_requires_evidence_nonendpoint_confidence_and_limitations(
    overrides: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "observation_id": "observation-access",
        "subject_ref": "page-root",
        "summary": "观察到受限访问提示",
        "evidence_refs": ["evidence-source"],
        "confidence": 0.42,
        "limitations": ["未提供受控身份"],
        "promotion_status": "unverified",
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        Observation.model_validate(values)


def test_inference_requires_complete_contract_and_utc_timestamp() -> None:
    values: dict[str, Any] = {
        "inference_id": "inference-example",
        "conclusion": "未来推断示例",
        "evidence_refs": ["evidence-source"],
        "confidence": 0.5,
        "producer": "future-engine",
        "method": "future-method",
        "created_at": OBSERVED_FROM,
    }
    inference = Inference.model_validate(values)
    assert inference.conclusion == "未来推断示例"

    for field in (
        "conclusion",
        "evidence_refs",
        "confidence",
        "producer",
        "method",
        "created_at",
    ):
        incomplete = values.copy()
        incomplete.pop(field)
        with pytest.raises(ValidationError):
            Inference.model_validate(incomplete)

    with pytest.raises(ValidationError):
        Inference.model_validate({**values, "created_at": datetime(2026, 7, 30)})


def test_knowledge_gap_reason_is_controlled() -> None:
    with pytest.raises(ValidationError):
        make_gap(reason_code="free_text_reason")


def test_match_hint_type_is_controlled_and_value_is_string() -> None:
    with pytest.raises(ValidationError):
        MatchHint(hint_type="arbitrary", value="value")
    with pytest.raises(ValidationError):
        MatchHint(hint_type="locator_parameter", value={"name": "提交"})


def test_structured_match_hints_require_canonical_json_strings() -> None:
    hint = MatchHint(hint_type="frame_ancestry", value='["main","child"]')
    assert hint.value == '["main","child"]'
    locator_parameter = MatchHint(
        hint_type="locator_parameter",
        value=(
            '{"parameters":{"exact":true,"name":"提交"},'
            '"strategy":"role"}'
        ),
    )
    assert locator_parameter.hint_type == "locator_parameter"

    with pytest.raises(ValidationError):
        MatchHint(hint_type="frame_ancestry", value='["main", "child"]')
    with pytest.raises(ValidationError):
        MatchHint(hint_type="locator_parameter", value="not-json")


@pytest.mark.parametrize(
    "value",
    [
        "[]",
        '[""]',
        '["main",1]',
        '{"frame":"main"}',
    ],
)
def test_frame_ancestry_hint_requires_nonempty_string_array(value: str) -> None:
    with pytest.raises(ValidationError):
        MatchHint(hint_type="frame_ancestry", value=value)


@pytest.mark.parametrize(
    "value",
    [
        "{}",
        '{"parameters":{"name":"提交"}}',
        '{"strategy":"role"}',
        '{"extra":true,"parameters":{"name":"提交"},"strategy":"role"}',
        '{"parameters":{"name":"提交"},"strategy":"unknown"}',
        '{"parameters":{},"strategy":"role"}',
        '{"parameters":{"nested":{"name":"提交"}},"strategy":"role"}',
        '{"parameters":{"items":["提交"]},"strategy":"role"}',
        '{"parameters":{"missing":null},"strategy":"role"}',
        '{"parameters":{"score":1e999},"strategy":"role"}',
    ],
)
def test_locator_parameter_hint_requires_fixed_scalar_shape(value: str) -> None:
    with pytest.raises(ValidationError):
        MatchHint(hint_type="locator_parameter", value=value)


@pytest.mark.parametrize(
    "hint_type",
    ["url", "tag", "role", "test_id"],
)
def test_plain_match_hint_requires_nonempty_noncontainer_string(
    hint_type: str,
) -> None:
    assert MatchHint(hint_type=hint_type, value="button").value == "button"
    with pytest.raises(ValidationError):
        MatchHint(hint_type=hint_type, value="")
    with pytest.raises(ValidationError):
        MatchHint(hint_type=hint_type, value='["button"]')
    with pytest.raises(ValidationError):
        MatchHint(hint_type=hint_type, value='{"role":"button"}')


def test_predicate_is_controlled() -> None:
    assert Fact(
        fact_id="fact-role",
        subject_ref="element-submit",
        predicate=Predicate.ELEMENT_ROLE,
        value="button",
        evidence_refs=["evidence-source"],
        observed_at=OBSERVED_FROM,
    ).predicate is Predicate.ELEMENT_ROLE

    with pytest.raises(ValidationError):
        make_fact(predicate="natural.language.field")


def test_fact_and_locator_reject_nonfinite_json_numbers() -> None:
    with pytest.raises(ValidationError):
        make_fact(value=float("nan"))
    with pytest.raises(ValidationError):
        make_locator(parameters={"x": float("inf")})


def test_position_locator_cannot_be_recommended() -> None:
    with pytest.raises(ValidationError):
        make_locator(
            strategy="position",
            source="diagnostic",
            stability="low",
            recommended=True,
        )


def test_generated_position_locator_is_allowed_when_not_recommended() -> None:
    locator = make_locator(
        strategy="position",
        source="generated",
        uniqueness="unverified",
        match_count=None,
        stability="low",
        recommended=False,
    )

    assert locator.source == "generated"


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "uniqueness": "multiple",
            "match_count": 2,
            "recommended": True,
        },
        {
            "uniqueness": "unverified",
            "match_count": 1,
            "recommended": False,
        },
        {
            "uniqueness": "unverified",
            "match_count": None,
            "recommended": True,
        },
    ],
)
def test_locator_recommendation_requires_verified_uniqueness(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        make_locator(**overrides)


@pytest.mark.parametrize(
    ("uniqueness", "match_count"),
    [
        ("unique", 2),
        ("multiple", 1),
    ],
)
def test_locator_uniqueness_matches_count(
    uniqueness: str,
    match_count: int,
) -> None:
    with pytest.raises(ValidationError):
        make_locator(uniqueness=uniqueness, match_count=match_count)


def test_time_fields_require_aware_utc_values_and_valid_ranges() -> None:
    with pytest.raises(ValidationError):
        make_exploration_run(started_at=datetime(2026, 7, 30))
    with pytest.raises(ValidationError):
        make_exploration_run(completed_at=OBSERVED_FROM - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        make_entity(observed_from=datetime(2026, 7, 30))
    with pytest.raises(ValidationError):
        make_entity(observed_to=OBSERVED_FROM - timedelta(seconds=1))


@pytest.mark.parametrize(
    ("field", "dangling_ref"),
    [
        ("entity_source", "evidence-missing"),
        ("entity_application", "app-missing"),
        ("locator_element", "element-missing"),
        ("locator_frame", "frame-missing"),
        ("locator_evidence", "evidence-missing"),
        ("fact_subject", "element-missing"),
        ("fact_object", "element-missing"),
        ("fact_evidence", "evidence-missing"),
        ("gap_subject", "page-missing"),
        ("gap_evidence", "evidence-missing"),
    ],
)
def test_package_rejects_dangling_references(
    field: str,
    dangling_ref: str,
) -> None:
    package = make_package()
    values = package.model_dump(mode="python")

    if field == "entity_source":
        values["entities"][0]["source_refs"] = [dangling_ref]
    elif field == "entity_application":
        values["entities"][0]["application_ref"] = dangling_ref
    elif field == "locator_element":
        values["locator_candidates"][0]["element_ref"] = dangling_ref
    elif field == "locator_frame":
        values["locator_candidates"][0]["frame_ref"] = dangling_ref
    elif field == "locator_evidence":
        values["locator_candidates"][0]["evidence_refs"] = [dangling_ref]
    elif field == "fact_subject":
        values["facts"][0]["subject_ref"] = dangling_ref
    elif field == "fact_object":
        values["facts"][0]["value"] = None
        values["facts"][0]["object_ref"] = dangling_ref
    elif field == "fact_evidence":
        values["facts"][0]["evidence_refs"] = [dangling_ref]
    elif field == "gap_subject":
        values["knowledge_gaps"] = [
            make_gap(subject_ref=dangling_ref).model_dump(mode="python")
        ]
        values["statistics"]["knowledge_gap_count"] = 1
    else:
        values["knowledge_gaps"] = [
            make_gap(evidence_refs=[dangling_ref]).model_dump(mode="python")
        ]
        values["statistics"]["knowledge_gap_count"] = 1

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


@pytest.mark.parametrize(
    ("collection", "id_field"),
    [
        ("entities", "entity_id"),
        ("locator_candidates", "locator_id"),
        ("evidence", "evidence_id"),
        ("facts", "fact_id"),
    ],
)
def test_package_requires_unique_ids(
    collection: str,
    id_field: str,
) -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    duplicate = values[collection][0].copy()
    values[collection].append(duplicate)
    count_field = {
        "entities": "entity_count",
        "locator_candidates": "locator_candidate_count",
        "evidence": "evidence_count",
        "facts": "fact_count",
    }[collection]
    values["statistics"][count_field] += 1

    assert duplicate[id_field]
    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_package_id_participates_in_global_id_uniqueness() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["package_id"] = values["entities"][0]["entity_id"]

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_sprint_two_package_requires_empty_inferences() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["inferences"] = [
        {
            "inference_id": "inference-example",
            "conclusion": "未来推断示例",
            "evidence_refs": ["evidence-source"],
            "confidence": 0.5,
            "producer": "future-engine",
            "method": "future-method",
            "created_at": OBSERVED_FROM,
        }
    ]
    values["statistics"]["inference_count"] = 1

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_package_statistics_equal_actual_collection_counts() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["statistics"]["fact_count"] = 0

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_partial_requires_stop_reason_and_completed_forbids_it() -> None:
    package = make_package()
    values = package.model_dump(mode="python")

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate({**values, "status": "partial"})
    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(
            {**values, "stop_reasons": ["collection_truncated"]}
        )
    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(
            {
                **values,
                "status": "partial",
                "stop_reasons": [""],
            }
        )

    partial = KnowledgePackage.model_validate(
        {
            **values,
            "status": "partial",
            "stop_reasons": ["collection_truncated"],
            "knowledge_gaps": [
                make_gap(
                    gap_id="gap-truncated",
                    reason_code="collection_truncated",
                ).model_dump(mode="python")
            ],
            "statistics": {
                **values["statistics"],
                "knowledge_gap_count": 1,
            },
        }
    )
    assert partial.status == "partial"


@pytest.mark.parametrize(
    ("collection_status", "exploration_status"),
    [
        ("partial", "partial"),
        ("failed", "failed"),
        ("completed", "cancelled"),
        ("partial", "completed"),
    ],
)
def test_completed_package_rejects_incomplete_source_statuses(
    collection_status: str,
    exploration_status: str,
) -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["exploration_run"]["collection_status"] = collection_status
    values["exploration_run"]["exploration_status"] = exploration_status

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_completed_package_rejects_collection_truncated_gap() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["knowledge_gaps"] = [
        make_gap(
            gap_id="gap-truncated",
            reason_code="collection_truncated",
        ).model_dump(mode="python")
    ]
    values["statistics"]["knowledge_gap_count"] = 1

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_partial_package_requires_collection_truncated_gap() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["status"] = "partial"
    values["stop_reasons"] = ["source_snapshot_partial"]

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


@pytest.mark.parametrize(
    ("collection_status", "exploration_status"),
    [
        ("completed", "completed"),
        ("partial", "partial"),
        ("failed", "failed"),
        ("completed", "cancelled"),
    ],
)
def test_partial_package_accepts_explicit_truncation_semantics(
    collection_status: str,
    exploration_status: str,
) -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["status"] = "partial"
    values["stop_reasons"] = ["source_or_conversion_truncated"]
    values["exploration_run"]["collection_status"] = collection_status
    values["exploration_run"]["exploration_status"] = exploration_status
    values["knowledge_gaps"] = [
        make_gap(
            gap_id="gap-truncated",
            reason_code="collection_truncated",
        ).model_dump(mode="python")
    ]
    values["statistics"]["knowledge_gap_count"] = 1

    partial = KnowledgePackage.model_validate(values)
    assert partial.status == "partial"


def test_package_enforces_approved_limits() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["limits"]["max_evidence_chars"] = 3

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_knowledge_limits_use_approved_defaults_and_bounds() -> None:
    limits = KnowledgeLimits()
    assert limits.model_dump() == {
        "max_evidence_chars": 500,
        "max_locators_per_element": 12,
        "max_facts": 150_000,
        "max_observations": 1_000,
        "max_knowledge_gaps": 1_000,
        "max_json_bytes": 50 * 1024 * 1024,
    }

    with pytest.raises(ValidationError):
        KnowledgeLimits(max_json_bytes=65_535)
    with pytest.raises(ValidationError):
        KnowledgeLimits(max_facts=1_000_001)


def test_knowledge_application_keeps_normalized_origins() -> None:
    package = make_package()

    assert package.application.allowed_origins == ["https://example.test"]
    assert package.application.authentication_origins == [
        "https://sso.example.test"
    ]


def test_evidence_must_match_exploration_snapshot() -> None:
    package = make_package()
    values = package.model_dump(mode="python")
    values["evidence"][0] = make_evidence(
        snapshot_sha256="b" * 64
    ).model_dump(mode="python")

    with pytest.raises(ValidationError):
        KnowledgePackage.model_validate(values)


def test_committed_knowledge_schema_matches_model_schema() -> None:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "ai_ui_explorer"
        / "knowledge"
        / "schema"
        / "knowledge-package-v1.schema.json"
    )
    committed = json.loads(schema_path.read_text(encoding="utf-8"))

    assert committed == KnowledgePackage.to_schema()


def test_committed_knowledge_schema_declares_draft_and_accepts_valid_package() -> None:
    validator = committed_knowledge_validator()
    payload = make_package().model_dump(mode="json")

    validator.validate(payload)
    assert (
        validator.schema["$schema"]
        == "https://json-schema.org/draft/2020-12/schema"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "fact_both_value_and_object",
        "fact_neither_value_nor_object",
        "nonempty_inferences",
        "recommended_multiple_locator",
        "recommended_position_locator",
        "counted_unverified_locator",
        "completed_with_stop_reason",
        "partial_without_stop_reason",
    ],
)
def test_committed_knowledge_schema_rejects_local_invariant_violations(
    mutation: str,
) -> None:
    payload = make_package().model_dump(mode="json")
    if mutation == "fact_both_value_and_object":
        payload["facts"][0]["object_ref"] = "element-submit"
    elif mutation == "fact_neither_value_nor_object":
        payload["facts"][0]["value"] = None
        payload["facts"][0]["object_ref"] = None
    elif mutation == "nonempty_inferences":
        payload["inferences"] = [
            {
                "inference_id": "inference-example",
                "conclusion": "未来推断示例",
                "evidence_refs": ["evidence-source"],
                "confidence": 0.5,
                "producer": "future-engine",
                "method": "future-method",
                "created_at": "2026-07-30T00:00:00Z",
            }
        ]
    elif mutation == "recommended_multiple_locator":
        payload["locator_candidates"][0].update(
            uniqueness="multiple",
            match_count=2,
            recommended=True,
        )
    elif mutation == "recommended_position_locator":
        payload["locator_candidates"][0].update(
            strategy="position",
            recommended=True,
        )
    elif mutation == "counted_unverified_locator":
        payload["locator_candidates"][0].update(
            uniqueness="unverified",
            match_count=1,
            recommended=False,
        )
    elif mutation == "completed_with_stop_reason":
        payload["stop_reasons"] = ["unexpected-truncation"]
    else:
        payload["status"] = "partial"
        payload["stop_reasons"] = []

    with pytest.raises(JsonSchemaValidationError):
        committed_knowledge_validator().validate(payload)


def committed_knowledge_validator() -> Draft202012Validator:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "ai_ui_explorer"
        / "knowledge"
        / "schema"
        / "knowledge-package-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def timezone_with_offset(*, hours: int) -> timezone:
    return timezone(timedelta(hours=hours))
