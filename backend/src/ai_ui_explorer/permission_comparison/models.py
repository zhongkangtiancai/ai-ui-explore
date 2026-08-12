"""Strict, serializable models for permission-aware exploration results."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal, Self, cast

from pydantic import Field, field_validator, model_validator

from ai_ui_explorer.exploration.authentication import AuthenticationPlan
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel

_SAFE_IDENTITY_ID = re.compile(r"^identity-[0-9]{1,20}$")
_SAFE_COMPARISON_ID = re.compile(r"^comparison-[0-9]{1,20}$")
_SAFE_EVIDENCE_ID = re.compile(r"^evidence-[a-z0-9-]{1,100}$")
_SENSITIVE_TERMS = (
    "password",
    "cookie",
    "token",
    "secret",
    "storage",
    "验证码",
    "密码",
    "令牌",
)


class IdentityRunState(StrEnum):
    CREATED = "created"
    PAUSED_FOR_HUMAN = "paused_for_human"
    COLLECTING = "collecting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObservationState(StrEnum):
    OBSERVED = "observed"
    NOT_OBSERVED = "not_observed"
    COLLECTION_INCOMPLETE = "collection_incomplete"
    AUTHENTICATION_UNVERIFIED = "authentication_unverified"
    COLLECTION_FAILED = "collection_failed"
    NOT_MATCHABLE = "not_matchable"


class DifferenceKind(StrEnum):
    OBSERVED_IN_ONLY_ONE_IDENTITY = "observed_in_only_one_identity"
    OBSERVED_IN_MULTIPLE_IDENTITIES = "observed_in_multiple_identities"
    SAFE_ATTRIBUTE_CHANGED = "safe_attribute_changed"
    LINK_TARGET_CHANGED = "link_target_changed"
    NOT_COMPARABLE = "not_comparable"


class DifferenceReliability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INCONCLUSIVE = "inconclusive"


class IdentityProfile(DeepFrozenModel):
    """A non-secret identity label plus optional manual-login configuration."""

    identity_id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=80)
    authentication_plan: AuthenticationPlan | None = None

    @field_validator("identity_id")
    @classmethod
    def validate_identity_id(cls, value: str) -> str:
        if _SAFE_IDENTITY_ID.fullmatch(value) is None:
            raise ValueError("identity ID must use the safe public format")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identity label must not be blank")
        lowered = normalized.casefold()
        if any(term in lowered for term in _SENSITIVE_TERMS):
            raise ValueError("identity label must not contain sensitive terms")
        return normalized


class EvidenceReference(DeepFrozenModel):
    """A bounded pointer to an already-redacted snapshot observation."""

    evidence_id: str = Field(min_length=1, max_length=120)
    snapshot_id: str = Field(min_length=1, max_length=120)
    snapshot_schema_version: Literal["1.0", "1.1"]
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    json_pointer: str = Field(min_length=1, max_length=1_024)
    excerpt: str = Field(min_length=1, max_length=500)

    @field_validator("evidence_id")
    @classmethod
    def validate_evidence_id(cls, value: str) -> str:
        if _SAFE_EVIDENCE_ID.fullmatch(value) is None:
            raise ValueError("evidence ID must use the safe public format")
        return value


class ElementEvidence(DeepFrozenModel):
    element_key: str = Field(min_length=1, max_length=300)
    frame_path: str = Field(min_length=1, max_length=500)
    tag: str = Field(min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=120)
    accessible_name: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=500)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=32)
    href: str | None = Field(default=None, max_length=2_048)
    locator_hints: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[EvidenceReference] = Field(min_length=1, max_length=12)


class PageEvidence(DeepFrozenModel):
    page_key: str = Field(min_length=1, max_length=2_048)
    elements: list[ElementEvidence] = Field(default_factory=list, max_length=20_000)
    evidence_refs: list[EvidenceReference] = Field(min_length=1, max_length=12)


class IdentityEvidenceBundle(DeepFrozenModel):
    identity_id: str = Field(min_length=1, max_length=32)
    state: IdentityRunState
    pages: list[PageEvidence] = Field(default_factory=list, max_length=100)
    reason_codes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("identity_id")
    @classmethod
    def validate_identity_id(cls, value: str) -> str:
        if _SAFE_IDENTITY_ID.fullmatch(value) is None:
            raise ValueError("identity ID must use the safe public format")
        return value


class VisibilityDifference(DeepFrozenModel):
    difference_id: str = Field(min_length=1, max_length=120)
    kind: DifferenceKind
    subject_key: str = Field(min_length=1, max_length=2_048)
    identity_states: dict[str, ObservationState] = Field(min_length=2, max_length=5)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=24)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    reliability: DifferenceReliability = DifferenceReliability.LOW

    @model_validator(mode="after")
    def force_inconclusive_reliability(self) -> Self:
        incomplete_states = {
            ObservationState.COLLECTION_INCOMPLETE,
            ObservationState.AUTHENTICATION_UNVERIFIED,
            ObservationState.COLLECTION_FAILED,
            ObservationState.NOT_MATCHABLE,
        }
        if any(state in incomplete_states for state in self.identity_states.values()):
            object.__setattr__(self, "reliability", DifferenceReliability.INCONCLUSIVE)
        return self


class PermissionComparisonResult(DeepFrozenModel):
    comparison_id: str = Field(min_length=1, max_length=40)
    status: Literal["completed", "partial", "failed", "cancelled"]
    identities: list[IdentityEvidenceBundle] = Field(min_length=2, max_length=5)
    differences: list[VisibilityDifference] = Field(default_factory=list, max_length=100_000)

    @field_validator("comparison_id")
    @classmethod
    def validate_comparison_id(cls, value: str) -> str:
        if _SAFE_COMPARISON_ID.fullmatch(value) is None:
            raise ValueError("comparison ID must use the safe public format")
        return value

    @model_validator(mode="after")
    def validate_unique_identities(self) -> Self:
        identity_ids = [bundle.identity_id for bundle in self.identities]
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("comparison identities must be unique")
        return self


class PermissionComparisonExport(PermissionComparisonResult):
    """The versioned, schema-validated JSON download contract."""

    schema_version: Literal["1.0"] = "1.0"

    @classmethod
    def to_schema(cls) -> dict[str, object]:
        return cast(dict[str, object], cls.model_json_schema())
