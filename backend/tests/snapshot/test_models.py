import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_ui_explorer.snapshot.models import (
    Bounds,
    ScrollResult,
    SnapshotDocument,
    SnapshotDocumentV1,
    SnapshotError,
    SnapshotLimits,
)

from .factories import (
    make_element,
    make_frame,
    make_legacy_snapshot,
    make_locator_candidate,
    make_oversized_snapshot,
    make_snapshot,
)

_SNAPSHOT_V1_1_SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "ai_ui_explorer"
    / "snapshot"
    / "schema"
    / "snapshot-v1.1.schema.json"
)


def _make_valid_locator_candidate(**overrides: object) -> object:
    values: dict[str, object] = {
        "locator_id": "locator-main-element-0-role",
        "element_ref": "element-0",
        "frame_ref": "main",
    }
    values.update(overrides)
    return make_locator_candidate(**values)


def _snapshot_with_locator_candidates(
    *, locator_candidates: list[object], **overrides: object
) -> SnapshotDocument:
    statistics: dict[str, object] = {
        "frame_count": 1,
        "completed_frame_count": 1,
        "failed_frame_count": 0,
        "element_count": 1,
        "scroll_container_count": 0,
        "redaction_count": 0,
        "redaction_categories": [],
        "locator_candidate_count": len(locator_candidates),
        "duration_ms": 1,
    }
    return make_snapshot(
        locator_candidates=locator_candidates,
        statistics=statistics,
        **overrides,
    )


def test_snapshot_limits_use_approved_defaults() -> None:
    limits = SnapshotLimits()

    assert limits.total_timeout_ms == 60_000
    assert limits.max_frames == 50
    assert limits.max_scroll_containers_per_frame == 20
    assert limits.max_scroll_rounds_per_container == 30
    assert limits.max_elements == 5_000
    assert limits.max_text_chars == 500
    assert limits.max_json_bytes == 10 * 1024 * 1024


def test_snapshot_rejects_completed_status_when_truncated() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(status="completed", truncated=True)


def test_snapshot_rejects_completed_status_when_errors_exist() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(
            errors=[
                {
                    "scope": "page",
                    "error_code": "TIMEOUT",
                    "message": "timed out",
                    "recoverable": True,
                    "occurred_at": "2026-07-29T00:00:01+00:00",
                }
            ]
        )


@pytest.mark.parametrize(
    "frame_overrides",
    [
        {"status": "partial"},
        {"status": "failed"},
        {
            "errors": [
                {
                    "scope": "frame",
                    "error_code": "FRAME_ERROR",
                    "message": "frame failed",
                    "recoverable": True,
                    "occurred_at": "2026-07-29T00:00:01+00:00",
                }
            ]
        },
        {"truncated": True},
        {
            "scroll_results": [
                {
                    "container_id": "results",
                    "label": "Results",
                    "rounds": 1,
                    "discovered_elements": 0,
                    "restored": True,
                    "truncated": False,
                    "stop_reason": "error",
                }
            ]
        },
        {
            "scroll_results": [
                {
                    "container_id": "results",
                    "label": "Results",
                    "rounds": 1,
                    "discovered_elements": 0,
                    "restored": True,
                    "truncated": True,
                    "stop_reason": "stable",
                }
            ]
        },
    ],
)
def test_snapshot_rejects_completed_status_when_a_frame_is_incomplete(
    frame_overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        make_snapshot(frames=[make_frame(**frame_overrides)])


@pytest.mark.parametrize(
    "stop_reason",
    [
        "max_frames",
        "max_scroll_containers",
        "max_elements",
        "max_text_chars",
        "round_limit",
        "deadline",
        "detached",
        "error",
    ],
)
def test_frame_rejects_completed_status_with_an_incomplete_stop_reason(
    stop_reason: str,
) -> None:
    with pytest.raises(ValidationError):
        make_frame(stop_reason=stop_reason)


@pytest.mark.parametrize(
    "stop_reason",
    ["round_limit", "max_elements", "deadline"],
)
def test_scroll_result_rejects_budget_stop_without_truncation(
    stop_reason: str,
) -> None:
    with pytest.raises(ValidationError):
        ScrollResult(
            container_id="root-scroll-0",
            label="document",
            rounds=1,
            discovered_elements=0,
            restored=True,
            truncated=False,
            stop_reason=stop_reason,
        )


@pytest.mark.parametrize(
    "stop_reason",
    ["round_limit", "max_elements", "deadline", "detached", "error"],
)
def test_frame_rejects_completed_status_with_incomplete_scroll_reason(
    stop_reason: str,
) -> None:
    with pytest.raises(ValidationError):
        make_frame(
            scroll_results=[
                {
                    "container_id": "root-scroll-0",
                    "label": "document",
                    "rounds": 1,
                    "discovered_elements": 0,
                    "restored": True,
                    "truncated": False,
                    "stop_reason": stop_reason,
                }
            ]
        )


def test_snapshot_error_rejects_non_utc_timestamps() -> None:
    with pytest.raises(ValidationError):
        SnapshotError(
            scope="page",
            error_code="TIMEOUT",
            message="timed out",
            recoverable=True,
            occurred_at="2026-07-29T08:00:01+08:00",
        )


def test_snapshot_requires_utc_datetimes_in_completion_order() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(started_at=datetime(2026, 7, 29, 0, 0, 1))

    with pytest.raises(ValidationError):
        make_snapshot(
            started_at="2026-07-29T00:00:02+00:00",
            completed_at="2026-07-29T00:00:01+00:00",
        )


def test_snapshot_requires_the_page_main_frame() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(
            page={
                "main_frame_id": "missing",
                "viewport_width": 1280,
                "viewport_height": 720,
                "language": "en",
            }
        )


def test_snapshot_rejects_duplicate_frame_ids() -> None:
    """Duplicate frame IDs make parent and locator references ambiguous."""
    duplicate = make_frame(
        frame_id="main",
        traversal_index=1,
        elements=[],
    )

    with pytest.raises(ValidationError):
        make_snapshot(frames=[make_frame(), duplicate])


def test_snapshot_rejects_missing_parent_frame_reference() -> None:
    """A non-null parent_frame_id must identify a frame in the document."""
    frame = make_frame(parent_frame_id="missing")

    with pytest.raises(ValidationError):
        make_snapshot(frames=[frame])


def test_snapshot_rejects_element_frame_id_that_disagrees_with_container() -> None:
    """Element ownership comes from its containing Frame, not its self-reported ID."""
    misplaced = make_frame(
        elements=[make_element(frame_id="child")],
    )
    child = make_frame(
        frame_id="child",
        parent_frame_id="main",
        traversal_index=1,
        depth=1,
        elements=[],
    )

    with pytest.raises(ValidationError):
        make_snapshot(frames=[misplaced, child])


def test_snapshot_rejects_element_count_above_limit() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(
            limits={"max_elements": 1},
            statistics={
                "frame_count": 1,
                "completed_frame_count": 1,
                "failed_frame_count": 0,
                "element_count": 2,
                "scroll_container_count": 0,
                "redaction_count": 0,
                "duration_ms": 1,
            },
        )


def test_nested_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Bounds(x=0, y=0, width=1, height=1, unexpected=True)


def test_current_snapshot_schema_is_version_1_1() -> None:
    snapshot = make_snapshot()

    assert snapshot.schema_version == "1.1"
    assert SnapshotDocument.to_schema()["properties"]["schema_version"]["const"] == "1.1"


def test_legacy_snapshot_model_accepts_version_1_0() -> None:
    payload = make_snapshot().model_dump(mode="json")
    payload["schema_version"] = "1.0"
    payload.pop("locator_candidates")
    payload["statistics"].pop("locator_candidate_count")
    payload["frames"][0]["elements"][0]["locator_hints"] = [
        {"strategy": "role", "value": "button"}
    ]

    legacy = SnapshotDocumentV1.model_validate(payload)

    assert legacy.schema_version == "1.0"


def test_legacy_snapshot_rejects_current_locator_candidates() -> None:
    payload = make_legacy_snapshot().model_dump(mode="json")
    payload["locator_candidates"] = []

    with pytest.raises(ValidationError):
        SnapshotDocumentV1.model_validate(payload)


def test_legacy_snapshot_rejects_current_locator_statistics() -> None:
    payload = make_legacy_snapshot().model_dump(mode="json")
    payload["statistics"]["locator_candidate_count"] = 0

    with pytest.raises(ValidationError):
        SnapshotDocumentV1.model_validate(payload)


def test_current_snapshot_rejects_legacy_element_locator_hints() -> None:
    """Snapshot 1.1 must use only flattened locator_candidates."""
    payload = make_snapshot().model_dump(mode="json")
    payload["frames"][0]["elements"][0]["locator_hints"] = [
        {"strategy": "role", "value": "button"}
    ]

    with pytest.raises(ValidationError):
        SnapshotDocument.model_validate(payload)


def test_snapshot_rejects_locator_with_missing_element_reference() -> None:
    with pytest.raises(ValidationError):
        _snapshot_with_locator_candidates(
            locator_candidates=[
                {
                    "locator_id": "locator-missing",
                    "element_ref": "missing",
                    "frame_ref": "main",
                    "strategy": "role",
                    "parameters": {"role": "button", "name": "Submit"},
                    "source": "observed",
                    "uniqueness": "unique",
                    "match_count": 1,
                    "stability": "high",
                    "confidence": 1.0,
                    "rank": 1,
                    "recommended": True,
                    "limitations": [],
                }
            ]
        )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            _make_valid_locator_candidate(),
            _make_valid_locator_candidate(
                locator_id="locator-main-element-0-role", rank=2
            ),
        ),
        (
            _make_valid_locator_candidate(),
            _make_valid_locator_candidate(locator_id="locator-main-element-0-role-second"),
        ),
    ],
)
def test_snapshot_rejects_duplicate_locator_ids_and_element_ranks(
    first: object, second: object
) -> None:
    with pytest.raises(ValidationError):
        _snapshot_with_locator_candidates(locator_candidates=[first, second])


@pytest.mark.parametrize(
    "candidate_overrides",
    [
        {"frame_ref": "missing"},
        {"frame_ref": "other"},
        {"uniqueness": "unique", "match_count": 2},
        {"uniqueness": "multiple", "match_count": 1},
        {"strategy": "position", "recommended": True},
        {"confidence": -0.1},
        {"confidence": 1.1},
    ],
)
def test_snapshot_rejects_invalid_locator_candidate_rules(
    candidate_overrides: dict[str, object],
) -> None:
    frames = [make_frame()]
    if candidate_overrides.get("frame_ref") == "other":
        frames.append(make_frame(frame_id="other", elements=[]))

    with pytest.raises(ValidationError):
        _snapshot_with_locator_candidates(
            frames=frames,
            locator_candidates=[_make_valid_locator_candidate(**candidate_overrides)],
        )


def test_snapshot_rejects_more_than_twelve_candidates_for_one_element() -> None:
    candidates = [
        _make_valid_locator_candidate(
            locator_id=f"locator-main-element-0-{rank}", rank=rank
        )
        for rank in range(1, 14)
    ]

    with pytest.raises(ValidationError):
        _snapshot_with_locator_candidates(locator_candidates=candidates)


def test_snapshot_accepts_locator_candidate_for_a_known_element() -> None:
    candidate = _make_valid_locator_candidate(
        locator_id="locator-main-element-0-role",
    )
    snapshot = _snapshot_with_locator_candidates(
        locator_candidates=[candidate],
    )

    assert snapshot.locator_candidates == [candidate]


def test_snapshot_rejects_incorrect_locator_candidate_statistics() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(
            locator_candidates=[_make_valid_locator_candidate()],
            statistics={
                "frame_count": 1,
                "completed_frame_count": 1,
                "failed_frame_count": 0,
                "element_count": 1,
                "scroll_container_count": 0,
                "redaction_count": 0,
                "redaction_categories": [],
                "locator_candidate_count": 0,
                "duration_ms": 1,
            },
        )


def test_snapshot_v1_1_schema_matches_model() -> None:
    committed = json.loads(_SNAPSHOT_V1_1_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed == SnapshotDocument.to_schema()


def test_snapshot_accepts_sorted_unique_redaction_categories() -> None:
    frame = make_frame(redaction_categories=["EMAIL", "TOKEN"])
    snapshot = make_snapshot(
        frames=[frame],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": 1,
            "scroll_container_count": 0,
            "redaction_count": 2,
            "redaction_categories": ["EMAIL", "TOKEN"],
            "duration_ms": 1,
        },
    )

    assert snapshot.frames[0].redaction_categories == ["EMAIL", "TOKEN"]
    assert snapshot.statistics.redaction_categories == ["EMAIL", "TOKEN"]


def test_snapshot_normalizes_redaction_categories_to_sorted_unique_values() -> None:
    frame = make_frame(redaction_categories=["TOKEN", "EMAIL", "TOKEN"])
    snapshot = make_snapshot(
        frames=[frame],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": 1,
            "scroll_container_count": 0,
            "redaction_count": 3,
            "redaction_categories": ["TOKEN", "EMAIL", "TOKEN"],
            "duration_ms": 1,
        },
    )

    assert snapshot.frames[0].redaction_categories == ["EMAIL", "TOKEN"]
    assert snapshot.statistics.redaction_categories == ["EMAIL", "TOKEN"]


def test_snapshot_normalizes_tuple_redaction_categories_after_validation() -> None:
    frame = make_frame(redaction_categories=("TOKEN", "EMAIL", "TOKEN"))
    snapshot = make_snapshot(
        frames=[frame],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": 1,
            "scroll_container_count": 0,
            "redaction_count": 3,
            "redaction_categories": ("TOKEN", "EMAIL", "TOKEN"),
            "duration_ms": 1,
        },
    )

    assert snapshot.frames[0].redaction_categories == ["EMAIL", "TOKEN"]
    assert snapshot.statistics.redaction_categories == ["EMAIL", "TOKEN"]


def test_oversized_factory_exceeds_the_requested_size_with_ordered_elements() -> None:
    snapshot = make_oversized_snapshot(10_000)
    traversal_indexes = [
        element.traversal_index for frame in snapshot.frames for element in frame.elements
    ]

    assert len(snapshot.model_dump_json().encode("utf-8")) > 10_000
    assert traversal_indexes == sorted(traversal_indexes)
