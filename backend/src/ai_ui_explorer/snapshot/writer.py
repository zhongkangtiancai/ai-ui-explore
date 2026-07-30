"""Deterministic size bounding and atomic persistence for page snapshots."""

import json
import os
import tempfile
from pathlib import Path

from .models import FrameSnapshot, SnapshotDocument, SnapshotError


class SnapshotTooLargeError(ValueError):
    """Raised when required snapshot metadata cannot fit the approved output limit."""


def compact_snapshot(snapshot: SnapshotDocument) -> SnapshotDocument:
    """Return a deterministic, bounded representation of ``snapshot``.

    Summaries and elements are the only lossy fields.  Their removal order is
    defined by traversal order so equivalent inputs always produce equivalent
    compacted documents.
    """
    if _encoded_size(snapshot) <= snapshot.limits.max_json_bytes:
        return _validated_snapshot(snapshot)

    frames = list(snapshot.frames)

    for frame_position in _frame_positions_descending(frames):
        frame = frames[frame_position]
        frames[frame_position] = frame.model_copy(update={"text_summary": ""})
        candidate = _partial_snapshot(snapshot, frames)
        if _encoded_size(candidate) <= snapshot.limits.max_json_bytes:
            return _with_longest_summary_prefix(snapshot, frames, frame_position)

    for frame_position in _frame_positions_descending(frames):
        frame = frames[frame_position]
        for element_position in range(len(frame.elements) - 1, -1, -1):
            elements = list(frames[frame_position].elements)
            del elements[element_position]
            frames[frame_position] = frames[frame_position].model_copy(
                update={"elements": elements}
            )
            candidate = _partial_snapshot(snapshot, frames)
            if _encoded_size(candidate) <= snapshot.limits.max_json_bytes:
                return candidate

    candidate = _partial_snapshot(snapshot, frames)
    if _encoded_size(candidate) <= snapshot.limits.max_json_bytes:
        return candidate
    raise SnapshotTooLargeError(
        "snapshot exceeds max_json_bytes even after all permitted compaction"
    )


def write_snapshot(snapshot: SnapshotDocument, output_dir: Path) -> Path:
    """Write a bounded snapshot through a validated sibling temporary file."""
    compacted = compact_snapshot(snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "snapshot.json"
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(_serialize(compacted))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        SnapshotDocument.model_validate_json(temporary_path.read_text(encoding="utf-8"))
        temporary_path.replace(output_path)
        temporary_path = None
        return output_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _with_longest_summary_prefix(
    snapshot: SnapshotDocument,
    frames: list[FrameSnapshot],
    frame_position: int,
) -> SnapshotDocument:
    """Restore the largest prefix of one summary that remains within the limit."""
    original_summary = snapshot.frames[frame_position].text_summary
    low = 0
    high = len(original_summary)

    while low < high:
        midpoint = (low + high + 1) // 2
        frames[frame_position] = frames[frame_position].model_copy(
            update={"text_summary": original_summary[:midpoint]}
        )
        if _encoded_size(_partial_snapshot(snapshot, frames)) <= snapshot.limits.max_json_bytes:
            low = midpoint
        else:
            high = midpoint - 1

    frames[frame_position] = frames[frame_position].model_copy(
        update={"text_summary": original_summary[:low]}
    )
    return _partial_snapshot(snapshot, frames)


def _partial_snapshot(
    snapshot: SnapshotDocument, frames: list[FrameSnapshot]
) -> SnapshotDocument:
    """Apply the required partial status and size-limit error to compacted data."""
    errors = [*snapshot.errors, _output_size_limit_error(snapshot)]
    remaining_element_refs = {
        (frame.frame_id, element.element_id)
        for frame in frames
        for element in frame.elements
    }
    locator_candidates = [
        candidate
        for candidate in snapshot.locator_candidates
        if (candidate.frame_ref, candidate.element_ref) in remaining_element_refs
    ]
    statistics = snapshot.statistics.model_copy(
        update={
            "element_count": sum(len(frame.elements) for frame in frames),
            "locator_candidate_count": len(locator_candidates),
        }
    )
    candidate = snapshot.model_copy(
        update={
            "frames": frames,
            "locator_candidates": locator_candidates,
            "statistics": statistics,
            "errors": errors,
            "status": "partial",
            "truncated": True,
        }
    )
    return _validated_snapshot(candidate)


def _output_size_limit_error(snapshot: SnapshotDocument) -> SnapshotError:
    return SnapshotError(
        scope="output",
        error_code="output_size_limit",
        message="Snapshot was compacted to satisfy max_json_bytes.",
        recoverable=True,
        occurred_at=snapshot.completed_at,
    )


def _frame_positions_descending(frames: list[FrameSnapshot]) -> list[int]:
    return sorted(
        range(len(frames)),
        key=lambda position: (frames[position].traversal_index, position),
        reverse=True,
    )


def _encoded_size(snapshot: SnapshotDocument) -> int:
    return len(_serialize(snapshot).encode("utf-8"))


def _validated_snapshot(snapshot: SnapshotDocument) -> SnapshotDocument:
    return SnapshotDocument.model_validate(snapshot.model_dump(mode="python"))


def _serialize(snapshot: SnapshotDocument) -> str:
    return json.dumps(
        snapshot.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
