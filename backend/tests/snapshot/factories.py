"""Deterministic factories for snapshot contract tests."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ai_ui_explorer.snapshot.models import (
    Bounds,
    ElementSnapshot,
    FrameSnapshot,
    SnapshotDocument,
    SnapshotDocumentV1,
    SnapshotLimits,
    SnapshotLocatorCandidate,
)

_SNAPSHOT_ID = UUID("12345678-1234-5678-1234-567812345678")
_STARTED_AT = datetime(2026, 7, 29, 0, 0, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 7, 29, 0, 0, 1, tzinfo=UTC)


def make_element(**overrides: Any) -> ElementSnapshot:
    data: dict[str, Any] = {
        "element_id": "element-0",
        "frame_id": "main",
        "traversal_index": 0,
        "tag": "button",
        "role": "button",
        "accessible_name": "Submit",
        "text": "Submit",
        "attributes": {"type": "submit"},
        "visible": True,
        "enabled": True,
        "checked": None,
        "selected": None,
        "expanded": None,
        "bounds": Bounds(x=0, y=0, width=100, height=32),
    }
    data.update(overrides)
    return ElementSnapshot.model_validate(data)


def make_frame(**overrides: Any) -> FrameSnapshot:
    data: dict[str, Any] = {
        "frame_id": "main",
        "parent_frame_id": None,
        "traversal_index": 0,
        "depth": 0,
        "name": "main",
        "url": "https://example.test/",
        "status": "completed",
        "text_summary": "Example page",
        "elements": [make_element()],
        "scroll_results": [],
        "errors": [],
        "truncated": False,
        "stop_reason": None,
        "redaction_count": 0,
        "redaction_categories": [],
    }
    data.update(overrides)
    return FrameSnapshot.model_validate(data)


def make_locator_candidate(**overrides: Any) -> SnapshotLocatorCandidate:
    values: dict[str, Any] = {
        "locator_id": "locator-root-element-0-role",
        "element_ref": "root-element-0",
        "frame_ref": "root",
        "strategy": "role",
        "parameters": {"role": "button", "name": "Submit", "exact": True},
        "source": "observed",
        "uniqueness": "unique",
        "match_count": 1,
        "stability": "high",
        "confidence": 1.0,
        "rank": 1,
        "recommended": True,
        "limitations": [],
    }
    values.update(overrides)
    return SnapshotLocatorCandidate.model_validate(values)


def make_snapshot(**overrides: Any) -> SnapshotDocument:
    frame = make_frame()
    data: dict[str, Any] = {
        "snapshot_id": _SNAPSHOT_ID,
        "status": "completed",
        "started_at": _STARTED_AT,
        "completed_at": _COMPLETED_AT,
        "source": {
            "requested_url": "https://example.test/",
            "final_url": "https://example.test/",
            "title": "Example page",
        },
        "limits": SnapshotLimits(),
        "statistics": {
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
        "page": {
            "main_frame_id": frame.frame_id,
            "viewport_width": 1280,
            "viewport_height": 720,
            "language": "en",
        },
        "frames": [frame],
        "errors": [],
        "truncated": False,
    }
    data.update(overrides)
    return SnapshotDocument.model_validate(data)


def make_legacy_snapshot(**overrides: Any) -> SnapshotDocumentV1:
    data = make_snapshot().model_dump(mode="json")
    data["schema_version"] = "1.0"
    data.pop("locator_candidates")
    data["statistics"].pop("locator_candidate_count")
    for frame in data["frames"]:
        for element in frame["elements"]:
            element["locator_hints"] = [{"strategy": "role", "value": "button"}]
    data.update(overrides)
    return SnapshotDocumentV1.model_validate(data)


def make_oversized_snapshot(max_json_bytes: int) -> SnapshotDocument:
    # Leave enough headroom for tests that subsequently replace the serialized
    # max_json_bytes value with a shorter boundary value.
    target_size = max_json_bytes + 1_024
    limits = SnapshotLimits(max_elements=100_000)
    elements = [make_element(text=_fixed_text(0))]
    frame = make_frame(elements=elements, text_summary=_fixed_text(0))
    snapshot = make_snapshot(
        limits=limits,
        frames=[frame],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": len(elements),
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "duration_ms": 1,
        },
    )
    while len(snapshot.model_dump_json().encode("utf-8")) <= target_size:
        traversal_index = len(elements)
        elements.append(
            make_element(
                element_id=f"element-{traversal_index}",
                text=_fixed_text(traversal_index),
                traversal_index=traversal_index,
            )
        )
        frame = make_frame(elements=elements, text_summary=_fixed_text(traversal_index))
        snapshot = make_snapshot(
            limits=limits,
            frames=[frame],
            statistics={
                "frame_count": 1,
                "completed_frame_count": 1,
                "failed_frame_count": 0,
                "element_count": len(elements),
                "scroll_container_count": 0,
                "redaction_count": 0,
                "redaction_categories": [],
                "duration_ms": 1,
            },
        )
    return snapshot


def _fixed_text(index: int) -> str:
    return f"summary-{index:06d}-" + ("x" * (500 - len("summary-000000-")))
