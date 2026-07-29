"""Real raw-observation test doubles for collector tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from ai_ui_explorer.snapshot.browser import (
    RawElementObservation,
    RawErrorObservation,
    RawFrameObservation,
    RawPageObservation,
    RawScrollResult,
)
from ai_ui_explorer.snapshot.models import Bounds, SnapshotLimits


class FakeSource:
    """Return deterministic raw observations without browser automation."""

    def __init__(
        self,
        observation: RawPageObservation,
        on_collect: Callable[[], None] | None = None,
    ) -> None:
        self._observation = observation
        self.on_collect = on_collect
        self.collect_calls = 0

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

    @classmethod
    def with_page_fields(cls, *, frame_id: str, language: str) -> FakeSource:
        return cls(
            _page(
                frames=[_completed_root(text="Visible page text", frame_id=frame_id)],
                language=language,
            )
        )

    @classmethod
    def with_invalid_root(cls) -> FakeSource:
        return cls(
            _page(
                frames=[replace(_completed_root(text="Visible page text"), traversal_index=-1)]
            )
        )

    @classmethod
    def with_one_success_and_one_invalid_child(cls) -> FakeSource:
        root = _completed_root(text="token=root-secret")
        invalid_child = replace(
            _completed_root(text="Child content", frame_id="child"),
            parent_frame_id="root",
            traversal_index=1,
            depth=-1,
            name="child",
        )
        return cls(_page(frames=[root, invalid_child]))

    @classmethod
    def with_deadline_partial(cls) -> FakeSource:
        deadline_error = RawErrorObservation(
            scope="frame",
            error_code="deadline_reached",
            message="Frame collection reached the global deadline.",
            recoverable=True,
            occurred_at=datetime(2026, 7, 29, tzinfo=UTC),
        )
        partial = replace(
            _completed_root(text="Visible page text"),
            status="partial",
            scroll_results=[
                RawScrollResult(
                    container_id="root-scroll-0",
                    label="document",
                    rounds=1,
                    discovered_elements=1,
                    restored=True,
                    truncated=True,
                    stop_reason="deadline",
                )
            ],
            errors=[deadline_error],
            truncated=True,
            stop_reason="deadline",
        )
        return cls(_page(frames=[partial], deadline_reached=True))

    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        self.collect_calls += 1
        if self.on_collect is not None:
            self.on_collect()
        return self._observation


def _page(
    *,
    frames: list[RawFrameObservation],
    language: str = "en",
    deadline_reached: bool = False,
) -> RawPageObservation:
    return RawPageObservation(
        final_url="https://example.test/final",
        title="Example",
        viewport_width=1280,
        viewport_height=720,
        language=language,
        frames=frames,
        errors=[],
        deadline_reached=deadline_reached,
    )


def _completed_root(*, text: str, frame_id: str = "root") -> RawFrameObservation:
    return RawFrameObservation(
        frame_id=frame_id,
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
