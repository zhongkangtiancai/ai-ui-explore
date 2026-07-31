"""Stable page-state fingerprints for bounded exploration deduplication."""

import hashlib
import json
from collections.abc import Sequence
from typing import cast

from pydantic import Field

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.snapshot.models import (
    AnySnapshotDocument,
    ElementSnapshot,
    ElementSnapshotV1,
    FrameSnapshot,
    FrameSnapshotV1,
)


class StateFingerprint(DeepFrozenModel):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    seen_before: bool
    truncated: bool


class StateDeduplicator:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def observe(self, snapshot: AnySnapshotDocument) -> StateFingerprint:
        current = fingerprint_snapshot(snapshot)
        seen_before = current.fingerprint in self._seen
        self._seen.add(current.fingerprint)
        return current.model_copy(update={"seen_before": seen_before})


def fingerprint_snapshot(snapshot: AnySnapshotDocument) -> StateFingerprint:
    frames = cast(
        Sequence[FrameSnapshot | FrameSnapshotV1],
        snapshot.frames,
    )
    payload = {
        "schema_version": snapshot.schema_version,
        "final_url": snapshot.source.final_url,
        "title": snapshot.source.title,
        "page": snapshot.page.model_dump(mode="json"),
        "frames": [
            {
                "frame_id": frame.frame_id,
                "parent_frame_id": frame.parent_frame_id,
                "depth": frame.depth,
                "name": frame.name,
                "url": frame.url,
                "status": frame.status,
                "text_summary": frame.text_summary[:500],
                "elements": _element_payloads(frame),
            }
            for frame in sorted(
                frames,
                key=lambda item: (item.depth, item.traversal_index, item.frame_id),
            )
        ],
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return StateFingerprint(
        fingerprint=hashlib.sha256(encoded).hexdigest(),
        seen_before=False,
        truncated=snapshot.truncated,
    )


def _element_payloads(
    frame: FrameSnapshot | FrameSnapshotV1,
) -> list[dict[str, object]]:
    elements = cast(
        Sequence[ElementSnapshot | ElementSnapshotV1],
        frame.elements,
    )
    return [
        {
            "tag": element.tag,
            "role": element.role,
            "accessible_name": element.accessible_name,
            "text": element.text,
            "visible": element.visible,
            "enabled": element.enabled,
        }
        for element in elements
    ]
