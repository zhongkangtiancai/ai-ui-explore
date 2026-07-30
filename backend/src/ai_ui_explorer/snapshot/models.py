"""Pydantic models for the versioned page snapshot contract."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FrameStopReason = Literal[
    "max_frames",
    "max_scroll_containers",
    "max_elements",
    "max_text_chars",
    "round_limit",
    "deadline",
    "detached",
    "error",
]

_TRUNCATING_FRAME_STOP_REASONS = frozenset(
    {
        "max_frames",
        "max_scroll_containers",
        "max_elements",
        "max_text_chars",
        "round_limit",
        "deadline",
    }
)
_TRUNCATING_SCROLL_STOP_REASONS = frozenset(
    {"round_limit", "max_elements", "deadline"}
)


class SnapshotLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_timeout_ms: int = Field(default=60_000, ge=1_000, le=600_000)
    max_frames: int = Field(default=50, ge=1, le=500)
    max_scroll_containers_per_frame: int = Field(default=20, ge=0, le=200)
    max_scroll_rounds_per_container: int = Field(default=30, ge=0, le=500)
    max_elements: int = Field(default=5_000, ge=1, le=100_000)
    max_text_chars: int = Field(default=500, ge=0, le=10_000)
    max_json_bytes: int = Field(default=10 * 1024 * 1024, ge=64 * 1024, le=100 * 1024 * 1024)


class Bounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class LocatorHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["role", "label", "testid", "id"]
    value: str


LocatorStrategy = Literal[
    "role",
    "label",
    "text",
    "placeholder",
    "alt",
    "title",
    "testid",
    "id",
    "name",
    "aria",
    "css",
    "xpath",
    "position",
]
LocatorParameter = str | bool | int | float


class SnapshotLocatorCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator_id: str
    element_ref: str
    frame_ref: str
    strategy: LocatorStrategy
    parameters: dict[str, LocatorParameter]
    source: Literal["observed", "generated"]
    uniqueness: Literal["unique", "multiple", "unverified"]
    match_count: int | None = Field(default=None, ge=0)
    stability: Literal["high", "medium", "low", "unknown"]
    confidence: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    recommended: bool
    limitations: list[str]


class ElementSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str
    frame_id: str
    traversal_index: int = Field(ge=0)
    tag: str
    role: str | None
    accessible_name: str | None
    text: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: Bounds | None
    locator_hints: list[LocatorHint]


class ScrollResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str
    label: str
    rounds: int = Field(ge=0)
    discovered_elements: int = Field(ge=0)
    restored: bool
    truncated: bool
    stop_reason: Literal[
        "stable",
        "end_reached",
        "round_limit",
        "max_elements",
        "deadline",
        "detached",
        "error",
    ]

    @model_validator(mode="after")
    def validate_truncation(self) -> Self:
        if (
            self.stop_reason in _TRUNCATING_SCROLL_STOP_REASONS
            and not self.truncated
        ):
            raise ValueError("budget and deadline scroll stops require truncation")
        return self


class SnapshotError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    error_code: str
    message: str
    recoverable: bool
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if not _is_utc(self.occurred_at):
            raise ValueError("error timestamps must use UTC")
        return self


class FrameSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str
    parent_frame_id: str | None
    traversal_index: int = Field(ge=0)
    depth: int = Field(ge=0)
    name: str
    url: str
    status: Literal["completed", "partial", "failed"]
    text_summary: str
    elements: list[ElementSnapshot]
    scroll_results: list[ScrollResult]
    errors: list[SnapshotError]
    truncated: bool
    stop_reason: FrameStopReason | None
    redaction_count: int = Field(ge=0)
    redaction_categories: list[str]

    @field_validator("redaction_categories")
    @classmethod
    def normalize_redaction_categories(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        has_incomplete_scroll = any(
            result.stop_reason not in {"stable", "end_reached"}
            or result.truncated
            for result in self.scroll_results
        )
        if self.status == "completed" and (
            self.truncated
            or self.errors
            or self.stop_reason is not None
            or has_incomplete_scroll
        ):
            raise ValueError(
                "completed frames cannot contain errors, truncation, or a stop reason"
            )
        if (
            self.stop_reason in _TRUNCATING_FRAME_STOP_REASONS
            and not self.truncated
        ):
            raise ValueError("budget and deadline stop reasons require truncation")
        return self


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_url: str
    final_url: str
    title: str


class PageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main_frame_id: str
    viewport_width: int = Field(ge=1)
    viewport_height: int = Field(ge=1)
    language: str | None


class SnapshotStatisticsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_count: int = Field(ge=0)
    completed_frame_count: int = Field(ge=0)
    failed_frame_count: int = Field(ge=0)
    element_count: int = Field(ge=0)
    scroll_container_count: int = Field(ge=0)
    redaction_count: int = Field(ge=0)
    redaction_categories: list[str]
    duration_ms: int = Field(ge=0)

    @field_validator("redaction_categories")
    @classmethod
    def normalize_redaction_categories(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class SnapshotStatistics(SnapshotStatisticsV1):
    locator_candidate_count: int = Field(default=0, ge=0)


class _SnapshotDocumentBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    status: Literal["completed", "partial"]
    started_at: datetime
    completed_at: datetime
    source: SourceSnapshot
    limits: SnapshotLimits
    statistics: SnapshotStatisticsV1
    page: PageSnapshot
    frames: list[FrameSnapshot]
    errors: list[SnapshotError]
    truncated: bool

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        has_incomplete_frame = any(
            frame.status != "completed"
            or frame.errors
            or frame.truncated
            or any(
                scroll_result.stop_reason == "error" or scroll_result.truncated
                for scroll_result in frame.scroll_results
            )
            for frame in self.frames
        )
        if self.status == "completed" and (
            self.truncated or self.errors or has_incomplete_frame
        ):
            raise ValueError("completed snapshots cannot contain errors or truncation")
        if not _is_utc(self.started_at) or not _is_utc(self.completed_at):
            raise ValueError("snapshot timestamps must use UTC")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.page.main_frame_id not in {frame.frame_id for frame in self.frames}:
            raise ValueError("page.main_frame_id must exist in frames")

        actual_element_count = sum(len(frame.elements) for frame in self.frames)
        if (
            self.statistics.element_count > self.limits.max_elements
            or actual_element_count > self.limits.max_elements
        ):
            raise ValueError("element count exceeds the approved limit")
        return self


class SnapshotDocumentV1(_SnapshotDocumentBase):
    schema_version: Literal["1.0"] = "1.0"

    @model_validator(mode="before")
    @classmethod
    def discard_current_locator_statistics(
        cls, value: object
    ) -> object:
        if not isinstance(value, dict):
            return value
        statistics = value.get("statistics")
        if not isinstance(statistics, dict) or "locator_candidate_count" not in statistics:
            return value
        normalized = dict(value)
        normalized["statistics"] = {
            key: statistic_value
            for key, statistic_value in statistics.items()
            if key != "locator_candidate_count"
        }
        return normalized


class SnapshotDocument(_SnapshotDocumentBase):
    schema_version: Literal["1.1"] = "1.1"
    statistics: SnapshotStatistics
    locator_candidates: list[SnapshotLocatorCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_locator_candidates(self) -> Self:
        locator_ids = [candidate.locator_id for candidate in self.locator_candidates]
        if len(locator_ids) != len(set(locator_ids)):
            raise ValueError("locator candidate IDs must be unique")

        element_ranks = [
            (candidate.element_ref, candidate.rank)
            for candidate in self.locator_candidates
        ]
        if len(element_ranks) != len(set(element_ranks)):
            raise ValueError("locator candidate element references and ranks must be unique")

        frame_ids = {frame.frame_id for frame in self.frames}
        element_frame_ids: dict[str, set[str]] = {}
        for frame in self.frames:
            for element in frame.elements:
                element_frame_ids.setdefault(element.element_id, set()).add(element.frame_id)

        locator_counts = Counter(
            candidate.element_ref for candidate in self.locator_candidates
        )
        if any(count > 12 for count in locator_counts.values()):
            raise ValueError("elements cannot have more than 12 locator candidates")

        for candidate in self.locator_candidates:
            if candidate.frame_ref not in frame_ids:
                raise ValueError("locator candidate frame_ref must exist in frames")
            if candidate.frame_ref not in element_frame_ids.get(candidate.element_ref, set()):
                raise ValueError(
                    "locator candidate element_ref must exist in the referenced frame"
                )
            if candidate.uniqueness == "unique" and candidate.match_count != 1:
                raise ValueError("unique locator candidates require match_count == 1")
            if candidate.uniqueness == "multiple" and (
                candidate.match_count is None or candidate.match_count < 2
            ):
                raise ValueError("multiple locator candidates require match_count >= 2")
            if candidate.strategy == "position" and candidate.recommended:
                raise ValueError("position locator candidates cannot be recommended")

        if self.statistics.locator_candidate_count != len(self.locator_candidates):
            raise ValueError(
                "statistics.locator_candidate_count must equal locator candidate count"
            )
        return self

    @classmethod
    def to_schema(cls) -> dict[str, object]:
        return cast(dict[str, object], cls.model_json_schema())


AnySnapshotDocument = SnapshotDocumentV1 | SnapshotDocument


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)
