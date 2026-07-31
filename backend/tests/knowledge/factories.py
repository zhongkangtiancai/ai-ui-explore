"""Deterministic factories for knowledge contract tests."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ai_ui_explorer.knowledge.manifest import ApplicationManifest
from ai_ui_explorer.knowledge.models import (
    Evidence,
    ExplorationRun,
    Fact,
    IdentityContext,
    KnowledgeApplication,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeLimits,
    KnowledgeLocator,
    KnowledgePackage,
    KnowledgeStatistics,
    MatchHint,
)
from ai_ui_explorer.knowledge.predicates import Predicate

SNAPSHOT_ID = UUID("12345678-1234-5678-1234-567812345678")
OBSERVED_FROM = datetime(2026, 7, 30, 0, 0, 0, tzinfo=UTC)
OBSERVED_TO = datetime(2026, 7, 30, 0, 0, 1, tzinfo=UTC)
SNAPSHOT_SHA256 = "a" * 64


def make_manifest(**overrides: Any) -> ApplicationManifest:
    values: dict[str, Any] = {
        "application_id": "example-app",
        "name": "示例应用",
        "environment": "test",
        "allowed_origins": ["https://example.test"],
        "authentication_origins": ["https://sso.example.test"],
    }
    values.update(overrides)
    return ApplicationManifest.model_validate(values)


def make_application(**overrides: Any) -> KnowledgeApplication:
    values: dict[str, Any] = {
        "application_id": "example-app",
        "name": "示例应用",
        "environment": "test",
        "manifest_schema_version": "1.0",
        "allowed_origins": ["https://example.test"],
        "authentication_origins": ["https://sso.example.test"],
    }
    values.update(overrides)
    return KnowledgeApplication.model_validate(values)


def make_identity_context(**overrides: Any) -> IdentityContext:
    values: dict[str, Any] = {
        "status": "not_provided",
        "identity_alias": None,
        "role_label": None,
        "authorization_scope": [],
    }
    values.update(overrides)
    return IdentityContext.model_validate(values)


def make_exploration_run(**overrides: Any) -> ExplorationRun:
    values: dict[str, Any] = {
        "exploration_run_id": "run-example",
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_schema_version": "1.1",
        "snapshot_sha256": SNAPSHOT_SHA256,
        "collection_status": "completed",
        "content_status": "insufficient_evidence",
        "access_status": "public",
        "exploration_status": "completed",
        "identity_context": make_identity_context(),
        "started_at": OBSERVED_FROM,
        "completed_at": OBSERVED_TO,
    }
    values.update(overrides)
    return ExplorationRun.model_validate(values)


def make_evidence(**overrides: Any) -> Evidence:
    values: dict[str, Any] = {
        "evidence_id": "evidence-source",
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_schema_version": "1.1",
        "snapshot_sha256": SNAPSHOT_SHA256,
        "json_pointer": "/frames/0/elements/0/role",
        "evidence_type": "element.role",
        "excerpt": "button",
    }
    values.update(overrides)
    return Evidence.model_validate(values)


def make_entity(**overrides: Any) -> KnowledgeEntity:
    values: dict[str, Any] = {
        "entity_id": "element-submit",
        "entity_type": "element",
        "label": "提交",
        "application_ref": "example-app",
        "source_refs": ["evidence-source"],
        "observed_from": OBSERVED_FROM,
        "observed_to": OBSERVED_TO,
        "match_hints": [MatchHint(hint_type="role", value="button")],
    }
    values.update(overrides)
    return KnowledgeEntity.model_validate(values)


def make_locator(**overrides: Any) -> KnowledgeLocator:
    values: dict[str, Any] = {
        "locator_id": "locator-submit-role",
        "element_ref": "element-submit",
        "frame_ref": "frame-main",
        "strategy": "role",
        "parameters": {"role": "button", "name": "提交", "exact": True},
        "source": "observed",
        "uniqueness": "unique",
        "match_count": 1,
        "stability": "high",
        "confidence": 1.0,
        "rank": 1,
        "recommended": True,
        "evidence_refs": ["evidence-source"],
        "limitations": [],
    }
    values.update(overrides)
    return KnowledgeLocator.model_validate(values)


def make_fact(**overrides: Any) -> Fact:
    values: dict[str, Any] = {
        "fact_id": "fact-element-role",
        "subject_ref": "element-submit",
        "predicate": Predicate.ELEMENT_ROLE,
        "value": "button",
        "object_ref": None,
        "evidence_refs": ["evidence-source"],
        "confidence": 1.0,
        "assertion_type": "observed",
        "observed_at": OBSERVED_FROM,
    }
    values.update(overrides)
    return Fact.model_validate(values)


def make_gap(**overrides: Any) -> KnowledgeGap:
    values: dict[str, Any] = {
        "gap_id": "gap-identity",
        "subject_ref": "page-root",
        "aspect": "permission.data_scope",
        "reason_code": "identity_not_available",
        "reason": "本次探索未提供受控身份",
        "evidence_refs": [],
        "verification": "使用获授权的测试身份进行对比探索",
    }
    values.update(overrides)
    return KnowledgeGap.model_validate(values)


def make_statistics(
    *,
    entities: list[KnowledgeEntity],
    locators: list[KnowledgeLocator],
    evidence: list[Evidence],
    facts: list[Fact],
    observations: list[object],
    inferences: list[object],
    gaps: list[KnowledgeGap],
    **overrides: Any,
) -> KnowledgeStatistics:
    values: dict[str, Any] = {
        "entity_count": len(entities),
        "locator_candidate_count": len(locators),
        "evidence_count": len(evidence),
        "fact_count": len(facts),
        "observation_count": len(observations),
        "inference_count": len(inferences),
        "knowledge_gap_count": len(gaps),
    }
    values.update(overrides)
    return KnowledgeStatistics.model_validate(values)


def make_package(**overrides: Any) -> KnowledgePackage:
    entities = [
        make_entity(
            entity_id="page-root",
            entity_type="page",
            label="示例页面",
            match_hints=[MatchHint(hint_type="url", value="https://example.test/")],
        ),
        make_entity(
            entity_id="frame-main",
            entity_type="frame",
            label="main",
            match_hints=[
                MatchHint(hint_type="frame_ancestry", value='["main"]')
            ],
        ),
        make_entity(),
    ]
    locators = [make_locator()]
    evidence = [make_evidence()]
    facts = [
        make_fact(),
        make_fact(
            fact_id="fact-element-located-in",
            predicate=Predicate.ELEMENT_LOCATED_IN,
            value=None,
            object_ref="frame-main",
        ),
    ]
    observations: list[object] = []
    inferences: list[object] = []
    gaps: list[KnowledgeGap] = []
    values: dict[str, Any] = {
        "schema_version": "1.0",
        "package_id": "kp-example",
        "status": "completed",
        "limits": KnowledgeLimits(),
        "application": make_application(),
        "exploration_run": make_exploration_run(),
        "entities": entities,
        "locator_candidates": locators,
        "evidence": evidence,
        "facts": facts,
        "observations": observations,
        "inferences": inferences,
        "knowledge_gaps": gaps,
        "statistics": make_statistics(
            entities=entities,
            locators=locators,
            evidence=evidence,
            facts=facts,
            observations=observations,
            inferences=inferences,
            gaps=gaps,
        ),
        "stop_reasons": [],
    }
    values.update(overrides)
    return KnowledgePackage.model_validate(values)
