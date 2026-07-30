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

from .factories import make_legacy_snapshot, make_oversized_snapshot, make_snapshot

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
