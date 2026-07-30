"""Strict immutable Application Knowledge Model records."""

import json
from collections import Counter
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.knowledge.manifest import normalize_origin_list
from ai_ui_explorer.knowledge.predicates import Predicate

FactValue = str | bool | int | float
LocatorParameter = str | bool | int | float
_JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


class EntityType(StrEnum):
    PAGE = "page"
    FRAME = "frame"
    ELEMENT = "element"


class SourceType(StrEnum):
    SNAPSHOT = "snapshot"


class CollectionStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ContentStatus(StrEnum):
    EXPECTED = "expected"
    UNEXPECTED = "unexpected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AccessStatus(StrEnum):
    PUBLIC = "public"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_IN_PROGRESS = "authentication_in_progress"
    AUTHENTICATED = "authenticated"
    PERMISSION_DENIED = "permission_denied"
    ANTI_AUTOMATION_BLOCKED = "anti_automation_blocked"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class ExplorationStatus(StrEnum):
    CREATED = "created"
    COLLECTING = "collecting"
    PAUSED_FOR_HUMAN = "paused_for_human"
    VERIFYING_AUTHENTICATION = "verifying_authentication"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class KnowledgeStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"


class LocatorStrategy(StrEnum):
    ROLE = "role"
    LABEL = "label"
    TEXT = "text"
    PLACEHOLDER = "placeholder"
    ALT = "alt"
    TITLE = "title"
    TESTID = "testid"
    ID = "id"
    NAME = "name"
    ARIA = "aria"
    CSS = "css"
    XPATH = "xpath"
    POSITION = "position"


class LocatorSource(StrEnum):
    OBSERVED = "observed"
    GENERATED = "generated"
    DIAGNOSTIC = "diagnostic"


class LocatorUniqueness(StrEnum):
    UNIQUE = "unique"
    MULTIPLE = "multiple"
    UNVERIFIED = "unverified"


class LocatorStability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class KnowledgeGapReason(StrEnum):
    NOT_OBSERVED = "not_observed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SNAPSHOT_VERSION_LIMITED = "snapshot_version_limited"
    AUTHENTICATION_REQUIRED = "authentication_required"
    IDENTITY_NOT_AVAILABLE = "identity_not_available"
    PERMISSION_DENIED = "permission_denied"
    ANTI_AUTOMATION_BLOCKED = "anti_automation_blocked"
    COLLECTION_TRUNCATED = "collection_truncated"
    UNSUPPORTED_IN_CURRENT_SPRINT = "unsupported_in_current_sprint"


class MatchHintType(StrEnum):
    URL = "url"
    FRAME_ANCESTRY = "frame_ancestry"
    TAG = "tag"
    ROLE = "role"
    TEST_ID = "test_id"
    LOCATOR_PARAMETER = "locator_parameter"


_STRUCTURED_MATCH_HINT_TYPES = frozenset(
    {
        MatchHintType.FRAME_ANCESTRY,
        MatchHintType.LOCATOR_PARAMETER,
    }
)


class _KnowledgeModel(DeepFrozenModel):
    model_config = ConfigDict(allow_inf_nan=False)


class MatchHint(_KnowledgeModel):
    hint_type: MatchHintType
    value: str

    @model_validator(mode="after")
    def validate_structured_value(self) -> Self:
        if self.hint_type not in _STRUCTURED_MATCH_HINT_TYPES:
            if not self.value.strip():
                raise ValueError("plain match hints require a non-empty value")
            try:
                parsed_plain_value = json.loads(self.value)
            except ValueError:
                return self
            if isinstance(parsed_plain_value, list | dict):
                raise ValueError("plain match hints cannot contain JSON containers")
            return self
        try:
            parsed = json.loads(self.value)
            canonical = json.dumps(
                parsed,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "structured match hints require canonical JSON"
            ) from error
        if self.value != canonical:
            raise ValueError("structured match hints require canonical JSON")
        if self.hint_type == MatchHintType.FRAME_ANCESTRY:
            if (
                not isinstance(parsed, list)
                or not parsed
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in parsed
                )
            ):
                raise ValueError(
                    "frame ancestry must be a non-empty JSON string array"
                )
            return self
        if not isinstance(parsed, dict) or set(parsed) != {
            "strategy",
            "parameters",
        }:
            raise ValueError(
                "locator parameter hints require strategy and parameters"
            )
        strategy = parsed["strategy"]
        parameters = parsed["parameters"]
        if (
            not isinstance(strategy, str)
            or strategy not in {item.value for item in LocatorStrategy}
        ):
            raise ValueError("locator parameter hint strategy is invalid")
        if not isinstance(parameters, dict) or not parameters:
            raise ValueError(
                "locator parameter hint parameters must be a non-empty object"
            )
        if any(
            not key
            or not isinstance(parameter, str | bool | int | float)
            or (
                isinstance(parameter, float)
                and not isfinite(parameter)
            )
            for key, parameter in parameters.items()
        ):
            raise ValueError(
                "locator parameter hint values must be finite JSON scalars"
            )
        return self


class KnowledgeLimits(_KnowledgeModel):
    max_evidence_chars: int = Field(default=500, ge=1, le=10_000)
    max_locators_per_element: int = Field(default=12, ge=1, le=100)
    max_facts: int = Field(default=150_000, ge=1, le=1_000_000)
    max_observations: int = Field(default=1_000, ge=0, le=10_000)
    max_knowledge_gaps: int = Field(default=1_000, ge=1, le=10_000)
    max_json_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=65_536,
        le=524_288_000,
    )


class KnowledgeApplication(_KnowledgeModel):
    application_id: str = Field(
        min_length=1,
        pattern=r"^[a-z][a-z0-9-]{0,63}$",
    )
    name: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=64)
    manifest_schema_version: Literal["1.0"]
    allowed_origins: list[str] = Field(min_length=1, max_length=100)
    authentication_origins: list[str] = Field(max_length=100)

    @field_validator("name", "environment")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("allowed_origins", "authentication_origins")
    @classmethod
    def normalize_origins(cls, value: list[str]) -> list[str]:
        return normalize_origin_list(value)

    @model_validator(mode="after")
    def validate_origin_roles(self) -> Self:
        if set(self.allowed_origins) & set(self.authentication_origins):
            raise ValueError(
                "target and authentication origins must not overlap"
            )
        return self


class IdentityContext(_KnowledgeModel):
    status: Literal["not_provided", "provided"]
    identity_alias: str | None
    role_label: str | None
    authorization_scope: list[str]


class ExplorationRun(_KnowledgeModel):
    exploration_run_id: str = Field(min_length=1)
    snapshot_id: UUID
    snapshot_schema_version: Literal["1.0", "1.1"]
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    collection_status: CollectionStatus
    content_status: ContentStatus
    access_status: AccessStatus
    exploration_status: ExplorationStatus
    identity_context: IdentityContext
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        _require_utc(self.started_at, "started_at")
        _require_utc(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        return self


class KnowledgeEntity(_KnowledgeModel):
    entity_id: str = Field(min_length=1)
    entity_type: EntityType
    label: str
    application_ref: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    observed_from: datetime
    observed_to: datetime
    match_hints: list[MatchHint]

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        _require_utc(self.observed_from, "observed_from")
        _require_utc(self.observed_to, "observed_to")
        if self.observed_to < self.observed_from:
            raise ValueError("observed_to must not be earlier than observed_from")
        return self


class KnowledgeLocator(_KnowledgeModel):
    locator_id: str = Field(min_length=1)
    element_ref: str = Field(min_length=1)
    frame_ref: str = Field(min_length=1)
    strategy: LocatorStrategy
    parameters: dict[str, LocatorParameter]
    source: LocatorSource
    uniqueness: LocatorUniqueness
    match_count: int | None = Field(default=None, ge=0)
    stability: LocatorStability
    confidence: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    recommended: bool
    evidence_refs: list[str] = Field(min_length=1)
    limitations: list[str]

    @model_validator(mode="after")
    def validate_locator_contract(self) -> Self:
        if self.uniqueness == LocatorUniqueness.UNIQUE and self.match_count != 1:
            raise ValueError("unique locators require match_count == 1")
        if self.uniqueness == LocatorUniqueness.MULTIPLE and (
            self.match_count is None or self.match_count < 2
        ):
            raise ValueError("multiple locators require match_count >= 2")
        if self.uniqueness == LocatorUniqueness.UNVERIFIED and (
            self.match_count is not None or self.recommended
        ):
            raise ValueError(
                "unverified locators require no match count and cannot be recommended"
            )
        if self.recommended and (
            self.uniqueness != LocatorUniqueness.UNIQUE
            or self.match_count != 1
        ):
            raise ValueError("recommended locators must be verified unique")
        if self.strategy == LocatorStrategy.POSITION and self.recommended:
            raise ValueError("position locators cannot be recommended")
        return self


class Evidence(_KnowledgeModel):
    evidence_id: str = Field(min_length=1)
    snapshot_id: UUID
    snapshot_schema_version: Literal["1.0", "1.1"]
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    json_pointer: str
    evidence_type: str = Field(min_length=1)
    excerpt: str


class Fact(_KnowledgeModel):
    fact_id: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    predicate: Predicate
    value: FactValue | None = None
    object_ref: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=1.0, le=1.0)
    assertion_type: Literal["observed"] = "observed"
    observed_at: datetime

    @model_validator(mode="after")
    def validate_fact_contract(self) -> Self:
        if (self.value is None) == (self.object_ref is None):
            raise ValueError("facts require exactly one of value and object_ref")
        _require_utc(self.observed_at, "observed_at")
        return self


class Observation(_KnowledgeModel):
    observation_id: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(gt=0, lt=1)
    limitations: list[str] = Field(min_length=1)
    promotion_status: Literal["unverified"] = "unverified"


class Inference(_KnowledgeModel):
    inference_id: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    producer: str = Field(min_length=1)
    method: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        _require_utc(value, "created_at")
        return value


class KnowledgeGap(_KnowledgeModel):
    gap_id: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    aspect: str = Field(min_length=1)
    reason_code: KnowledgeGapReason
    reason: str = Field(min_length=1)
    evidence_refs: list[str]
    verification: str = Field(min_length=1)


class KnowledgeStatistics(_KnowledgeModel):
    entity_count: int = Field(ge=0)
    locator_candidate_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    fact_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    inference_count: int = Field(ge=0)
    knowledge_gap_count: int = Field(ge=0)


class KnowledgePackage(_KnowledgeModel):
    schema_version: Literal["1.0"] = "1.0"
    package_id: str = Field(min_length=1)
    status: KnowledgeStatus
    limits: KnowledgeLimits
    application: KnowledgeApplication
    exploration_run: ExplorationRun
    entities: list[KnowledgeEntity]
    locator_candidates: list[KnowledgeLocator]
    evidence: list[Evidence]
    facts: list[Fact]
    observations: list[Observation]
    inferences: list[Inference]
    knowledge_gaps: list[KnowledgeGap]
    statistics: KnowledgeStatistics
    stop_reasons: list[str]

    @model_validator(mode="after")
    def validate_package_contract(self) -> Self:
        self._validate_status()
        self._validate_unique_ids()
        self._validate_references()
        self._validate_statistics()
        self._validate_limits()
        return self

    def _validate_status(self) -> None:
        if self.inferences:
            raise ValueError("Sprint 2 knowledge packages require empty inferences")
        has_truncation_gap = any(
            gap.reason_code == KnowledgeGapReason.COLLECTION_TRUNCATED
            for gap in self.knowledge_gaps
        )
        source_is_complete = (
            self.exploration_run.collection_status
            == CollectionStatus.COMPLETED
            and self.exploration_run.exploration_status
            == ExplorationStatus.COMPLETED
        )
        if self.status == KnowledgeStatus.PARTIAL:
            if not self.stop_reasons or any(
                not reason.strip() for reason in self.stop_reasons
            ):
                raise ValueError(
                    "partial knowledge packages require non-empty stop reasons"
                )
            if not has_truncation_gap:
                raise ValueError(
                    "partial knowledge packages require a collection_truncated gap"
                )
            return
        if self.stop_reasons or has_truncation_gap:
            raise ValueError(
                "completed knowledge packages cannot contain truncation semantics"
            )
        if not source_is_complete:
            raise ValueError(
                "completed knowledge packages require completed source statuses"
            )

    def _validate_unique_ids(self) -> None:
        id_groups = (
            [self.package_id],
            [self.application.application_id],
            [self.exploration_run.exploration_run_id],
            [entity.entity_id for entity in self.entities],
            [locator.locator_id for locator in self.locator_candidates],
            [item.evidence_id for item in self.evidence],
            [item.fact_id for item in self.facts],
            [item.observation_id for item in self.observations],
            [item.inference_id for item in self.inferences],
            [item.gap_id for item in self.knowledge_gaps],
        )
        all_ids: list[str] = []
        for ids in id_groups:
            if len(ids) != len(set(ids)):
                raise ValueError("knowledge record IDs must be unique")
            all_ids.extend(ids)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("knowledge record IDs must be globally unique")

    def _validate_references(self) -> None:
        evidence_ids = {item.evidence_id for item in self.evidence}
        entity_types = {
            entity.entity_id: entity.entity_type for entity in self.entities
        }
        locator_ids = {locator.locator_id for locator in self.locator_candidates}
        subject_ids = {
            self.application.application_id,
            self.exploration_run.exploration_run_id,
            *entity_types,
            *locator_ids,
        }

        for entity in self.entities:
            if entity.application_ref != self.application.application_id:
                raise ValueError("entity application_ref must resolve to application")
            _require_subset(entity.source_refs, evidence_ids, "entity source_refs")

        element_ids = {
            entity_id
            for entity_id, entity_type in entity_types.items()
            if entity_type == EntityType.ELEMENT
        }
        frame_ids = {
            entity_id
            for entity_id, entity_type in entity_types.items()
            if entity_type == EntityType.FRAME
        }
        element_ranks: set[tuple[str, int]] = set()
        for locator in self.locator_candidates:
            if locator.element_ref not in element_ids:
                raise ValueError(
                    "locator element_ref must resolve to an Element entity"
                )
            if locator.frame_ref not in frame_ids:
                raise ValueError(
                    "locator frame_ref must resolve to a Frame entity"
                )
            rank_key = (locator.element_ref, locator.rank)
            if rank_key in element_ranks:
                raise ValueError("locator ranks must be unique per element")
            element_ranks.add(rank_key)
            _require_subset(
                locator.evidence_refs,
                evidence_ids,
                "locator evidence_refs",
            )

        for fact in self.facts:
            _require_member(fact.subject_ref, subject_ids, "fact subject_ref")
            if fact.object_ref is not None:
                _require_member(fact.object_ref, subject_ids, "fact object_ref")
            _require_subset(fact.evidence_refs, evidence_ids, "fact evidence_refs")

        for observation in self.observations:
            _require_member(
                observation.subject_ref,
                subject_ids,
                "observation subject_ref",
            )
            _require_subset(
                observation.evidence_refs,
                evidence_ids,
                "observation evidence_refs",
            )

        for gap in self.knowledge_gaps:
            _require_member(gap.subject_ref, subject_ids, "gap subject_ref")
            _require_subset(gap.evidence_refs, evidence_ids, "gap evidence_refs")

        run = self.exploration_run
        for item in self.evidence:
            if (
                item.snapshot_id != run.snapshot_id
                or item.snapshot_schema_version != run.snapshot_schema_version
                or item.snapshot_sha256 != run.snapshot_sha256
            ):
                raise ValueError(
                    "evidence source must match the exploration snapshot"
                )

    def _validate_statistics(self) -> None:
        expected = {
            "entity_count": len(self.entities),
            "locator_candidate_count": len(self.locator_candidates),
            "evidence_count": len(self.evidence),
            "fact_count": len(self.facts),
            "observation_count": len(self.observations),
            "inference_count": len(self.inferences),
            "knowledge_gap_count": len(self.knowledge_gaps),
        }
        if self.statistics.model_dump() != expected:
            raise ValueError(
                "knowledge statistics must equal actual collection counts"
            )

    def _validate_limits(self) -> None:
        if any(
            len(item.excerpt) > self.limits.max_evidence_chars
            for item in self.evidence
        ):
            raise ValueError("evidence excerpt exceeds the approved limit")
        locator_counts = Counter(
            locator.element_ref for locator in self.locator_candidates
        )
        if any(
            count > self.limits.max_locators_per_element
            for count in locator_counts.values()
        ):
            raise ValueError("element locator count exceeds the approved limit")
        if len(self.facts) > self.limits.max_facts:
            raise ValueError("fact count exceeds the approved limit")
        if len(self.observations) > self.limits.max_observations:
            raise ValueError("observation count exceeds the approved limit")
        if len(self.knowledge_gaps) > self.limits.max_knowledge_gaps:
            raise ValueError("knowledge gap count exceeds the approved limit")

    @classmethod
    def to_schema(cls) -> dict[str, object]:
        schema = cast(dict[str, object], cls.model_json_schema())
        schema["$schema"] = _JSON_SCHEMA_DRAFT
        definitions = _schema_object(schema["$defs"])
        fact_schema = _schema_object(definitions["Fact"])
        fact_schema["oneOf"] = [
            {
                "properties": {
                    "value": {"not": {"type": "null"}},
                    "object_ref": {"type": "null"},
                },
                "required": ["value"],
            },
            {
                "properties": {
                    "value": {"type": "null"},
                    "object_ref": {"minLength": 1, "type": "string"},
                },
                "required": ["object_ref"],
            },
        ]

        locator_schema = _schema_object(definitions["KnowledgeLocator"])
        locator_schema["allOf"] = [
            {
                "if": {
                    "properties": {"recommended": {"const": True}},
                    "required": ["recommended"],
                },
                "then": {
                    "properties": {
                        "uniqueness": {"const": "unique"},
                        "match_count": {"const": 1},
                    },
                    "required": ["uniqueness", "match_count"],
                },
            },
            {
                "if": {
                    "properties": {"strategy": {"const": "position"}},
                    "required": ["strategy"],
                },
                "then": {
                    "properties": {"recommended": {"const": False}},
                    "required": ["recommended"],
                },
            },
            {
                "if": {
                    "properties": {"uniqueness": {"const": "unverified"}},
                    "required": ["uniqueness"],
                },
                "then": {
                    "properties": {
                        "match_count": {"const": None},
                        "recommended": {"const": False},
                    },
                    "required": ["match_count", "recommended"],
                },
            },
        ]

        properties = _schema_object(schema["properties"])
        _schema_object(properties["inferences"])["maxItems"] = 0
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"status": {"const": "completed"}},
                    "required": ["status"],
                },
                "then": {
                    "properties": {"stop_reasons": {"maxItems": 0}},
                    "required": ["stop_reasons"],
                },
            },
            {
                "if": {
                    "properties": {"status": {"const": "partial"}},
                    "required": ["status"],
                },
                "then": {
                    "properties": {"stop_reasons": {"minItems": 1}},
                    "required": ["stop_reasons"],
                },
            },
        ]
        return schema


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")


def _require_subset(
    values: list[str],
    known_values: set[str],
    field_name: str,
) -> None:
    if not set(values) <= known_values:
        raise ValueError(f"{field_name} must resolve inside the package")


def _require_member(value: str, known_values: set[str], field_name: str) -> None:
    if value not in known_values:
        raise ValueError(f"{field_name} must resolve inside the package")


def _schema_object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value)
