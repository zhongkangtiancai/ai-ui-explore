"""Tests for deterministic snapshot compaction and persistence."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotDocumentV1
from ai_ui_explorer.snapshot.writer import (
    SnapshotTooLargeError,
    compact_snapshot,
    write_snapshot,
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
_SNAPSHOT_V1_SCHEMA_PATH = _SNAPSHOT_V1_1_SCHEMA_PATH.with_name("snapshot-v1.schema.json")


def test_writer_creates_schema_valid_json_atomically(tmp_path: Path) -> None:
    """A completed snapshot is persisted as the single final artifact."""
    output = write_snapshot(make_snapshot(), tmp_path / "result")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert output == tmp_path / "result" / "snapshot.json"
    assert payload["schema_version"] == "1.1"
    assert SnapshotDocument.model_validate(payload).snapshot_id == make_snapshot().snapshot_id
    assert not list(output.parent.glob("*.tmp"))


def test_writer_output_validates_with_snapshot_v1_1_schema(tmp_path: Path) -> None:
    output = write_snapshot(make_snapshot(), tmp_path / "result")
    schema = json.loads(_SNAPSHOT_V1_1_SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(json.loads(output.read_text(encoding="utf-8")))


def test_legacy_snapshot_validates_with_committed_v1_schema() -> None:
    payload = make_legacy_snapshot().model_dump(mode="json")
    schema = json.loads(_SNAPSHOT_V1_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert "locator_candidates" not in payload
    assert "locator_candidate_count" not in payload["statistics"]
    Draft202012Validator(schema).validate(payload)
    assert SnapshotDocumentV1.model_validate(payload).schema_version == "1.0"


def test_compaction_marks_snapshot_partial_and_keeps_within_limit() -> None:
    """Oversized data is predictably reduced into a bounded partial snapshot."""
    snapshot = _with_output_limit(make_oversized_snapshot(max_json_bytes=65_536), 65_536)

    compacted = compact_snapshot(snapshot)
    encoded = compacted.model_dump_json().encode("utf-8")

    assert len(encoded) <= 65_536
    assert compacted.status == "partial"
    assert compacted.truncated is True
    assert [error.error_code for error in compacted.errors] == ["output_size_limit"]


def test_compaction_removes_highest_element_indexes_first() -> None:
    """A compaction must retain a prefix of the traversal order, never a suffix."""
    compacted = compact_snapshot(
        _with_output_limit(make_oversized_snapshot(max_json_bytes=65_536), 65_536)
    )
    indexes = [element.traversal_index for frame in compacted.frames for element in frame.elements]

    assert indexes == list(range(len(indexes)))
    assert compacted.statistics.element_count == len(indexes)


def test_compaction_removes_locators_for_removed_elements() -> None:
    """Element compaction must not leave dangling locator references or stale counts."""
    snapshot = _with_locator_for_each_element(
        _with_output_limit(make_oversized_snapshot(max_json_bytes=70_000), 65_536)
    )

    compacted = compact_snapshot(snapshot)
    element_ids = {
        element.element_id for frame in compacted.frames for element in frame.elements
    }

    assert len(element_ids) < snapshot.statistics.element_count
    assert all(
        candidate.element_ref in element_ids
        for candidate in compacted.locator_candidates
    )
    assert compacted.statistics.locator_candidate_count == len(
        compacted.locator_candidates
    )
    assert SnapshotDocument.model_validate(
        compacted.model_dump(mode="python")
    ) == compacted


def test_compaction_counts_elements_even_when_ids_repeat() -> None:
    """Statistics must count element records, not assume element IDs are unique."""
    snapshot = _with_output_limit(
        make_oversized_snapshot(max_json_bytes=70_000),
        65_536,
    )
    payload = snapshot.model_dump(mode="python")
    for element in payload["frames"][0]["elements"]:
        element["element_id"] = "repeated-element-id"
    snapshot = SnapshotDocument.model_validate(payload)

    compacted = compact_snapshot(snapshot)
    actual_element_count = sum(
        len(frame.elements) for frame in compacted.frames
    )

    assert actual_element_count > 1
    assert compacted.statistics.element_count == actual_element_count


def test_compaction_closes_locator_references_with_repeated_ids_across_frames() -> None:
    """Reference closure must include frame_ref when element IDs repeat."""
    snapshot = _with_output_limit(
        make_oversized_snapshot(max_json_bytes=70_000),
        65_536,
    )
    child = make_frame(
        frame_id="child",
        parent_frame_id="main",
        traversal_index=1,
        depth=1,
        elements=[make_element(element_id="element-0", frame_id="child")],
    )
    payload = snapshot.model_dump(mode="python")
    payload["frames"].append(child.model_dump(mode="python"))
    payload["statistics"]["frame_count"] = 2
    payload["statistics"]["completed_frame_count"] = 2
    payload["statistics"]["element_count"] += 1
    payload["locator_candidates"] = [
        make_locator_candidate(
            locator_id="locator-child-element-0-role",
            element_ref="element-0",
            frame_ref="child",
        ).model_dump(mode="python")
    ]
    payload["statistics"]["locator_candidate_count"] = 1
    snapshot = SnapshotDocument.model_validate(payload)

    compacted = compact_snapshot(snapshot)
    remaining_refs = {
        (frame.frame_id, element.element_id)
        for frame in compacted.frames
        for element in frame.elements
    }

    assert all(
        (candidate.frame_ref, candidate.element_ref) in remaining_refs
        for candidate in compacted.locator_candidates
    )


def test_compaction_preserves_redaction_audit_categories() -> None:
    snapshot = _with_output_limit(
        make_oversized_snapshot(max_json_bytes=65_536),
        65_536,
    )
    frame = snapshot.frames[0].model_copy(
        update={
            "redaction_count": 1,
            "redaction_categories": ["CASE_REFERENCE"],
        }
    )
    snapshot = snapshot.model_copy(
        update={
            "frames": [frame],
            "statistics": snapshot.statistics.model_copy(
                update={
                    "redaction_count": 1,
                    "redaction_categories": ["CASE_REFERENCE"],
                }
            ),
        }
    )

    compacted = compact_snapshot(snapshot)

    assert compacted.frames[0].redaction_categories == ["CASE_REFERENCE"]
    assert compacted.statistics.redaction_categories == ["CASE_REFERENCE"]


def test_compaction_fails_when_required_contract_and_error_cannot_fit() -> None:
    """Fields outside the permitted compaction scope produce an explicit failure."""
    snapshot = make_snapshot(
        limits={"max_json_bytes": 65_536},
        source={
            "requested_url": "https://example.test/",
            "final_url": "https://example.test/",
            "title": "x" * 70_000,
        }
    )

    with pytest.raises(SnapshotTooLargeError):
        compact_snapshot(snapshot)


def _with_output_limit(snapshot: SnapshotDocument, max_json_bytes: int) -> SnapshotDocument:
    return snapshot.model_copy(
        update={"limits": snapshot.limits.model_copy(update={"max_json_bytes": max_json_bytes})}
    )


def _with_locator_for_each_element(snapshot: SnapshotDocument) -> SnapshotDocument:
    candidates = [
        make_locator_candidate(
            locator_id=f"locator-{element.element_id}-role",
            element_ref=element.element_id,
            frame_ref=element.frame_id,
        )
        for frame in snapshot.frames
        for element in frame.elements
    ]
    payload = snapshot.model_dump(mode="python")
    payload["locator_candidates"] = [
        candidate.model_dump(mode="python") for candidate in candidates
    ]
    payload["statistics"]["locator_candidate_count"] = len(candidates)
    return SnapshotDocument.model_validate(payload)
