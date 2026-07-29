"""Real raw-observation test doubles for collector tests."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_ui_explorer.snapshot.browser import (
    RawElementObservation,
    RawErrorObservation,
    RawFrameObservation,
    RawPageObservation,
)
from ai_ui_explorer.snapshot.models import Bounds, SnapshotLimits


class FakeSource:
    """Return deterministic raw observations without browser automation."""

    def __init__(self, observation: RawPageObservation) -> None:
        self._observation = observation

    @classmethod
    def with_one_success_and_one_failure(cls) -> FakeSource:
        completed = _completed_root(text="token=root-secret")
        failed = RawFrameObservation(
            frame_id="child",
            parent_frame_id="root",
            traversal_index=1,
            depth=1,
            name="child",
            url="https://example.test/child",
            status="failed",
            text_summary="",
            elements=[],
            scroll_results=[],
            errors=[
                RawErrorObservation(
                    scope="frame",
                    error_code="frame_unavailable",
                    message="Child frame could not be observed.",
                    recoverable=True,
                    occurred_at=datetime(2026, 7, 29, tzinfo=UTC),
                )
            ],
            truncated=False,
            stop_reason="error",
        )
        return cls(_page(frames=[completed, failed]))

    @classmethod
    def with_text(cls, value: str) -> FakeSource:
        return cls(_page(frames=[_completed_root(text=value)]))

    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        return self._observation


def _page(*, frames: list[RawFrameObservation]) -> RawPageObservation:
    return RawPageObservation(
        final_url="https://example.test/final",
        title="Example",
        viewport_width=1280,
        viewport_height=720,
        language="en",
        frames=frames,
        errors=[],
        deadline_reached=False,
    )


def _completed_root(*, text: str) -> RawFrameObservation:
    return RawFrameObservation(
        frame_id="root",
        parent_frame_id=None,
        traversal_index=0,
        depth=0,
        name="main",
        url="https://example.test/final",
        status="completed",
        text_summary=text,
        elements=[
            RawElementObservation(
                traversal_index=0,
                tag="button",
                role="button",
                accessible_name="Continue",
                text=text,
                attributes={"data-testid": "continue"},
                visible=True,
                enabled=True,
                checked=None,
                selected=None,
                expanded=None,
                bounds=Bounds(x=0, y=0, width=100, height=32),
                locator_hints=(),
            )
        ],
        scroll_results=[],
        errors=[],
        truncated=False,
        stop_reason=None,
    )
