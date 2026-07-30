from datetime import datetime

import pytest
from pydantic import ValidationError

from ai_ui_explorer.snapshot.models import (
    Bounds,
    ScrollResult,
    SnapshotDocument,
    SnapshotError,
    SnapshotLimits,
)

from .factories import make_frame, make_oversized_snapshot, make_snapshot


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


def test_snapshot_schema_is_versioned() -> None:
    schema = SnapshotDocument.to_schema()

    assert schema["properties"]["schema_version"]["default"] == "1.0"
    assert schema["properties"]["status"]["enum"] == ["completed", "partial"]


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
