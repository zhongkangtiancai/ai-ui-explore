from datetime import datetime

import pytest
from pydantic import ValidationError

from ai_ui_explorer.snapshot.models import Bounds, SnapshotDocument, SnapshotLimits

from .factories import make_oversized_snapshot, make_snapshot


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


def test_oversized_factory_exceeds_the_requested_size_with_ordered_elements() -> None:
    snapshot = make_oversized_snapshot(10_000)
    traversal_indexes = [
        element.traversal_index for frame in snapshot.frames for element in frame.elements
    ]

    assert len(snapshot.model_dump_json().encode("utf-8")) > 10_000
    assert traversal_indexes == sorted(traversal_indexes)
