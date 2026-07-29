"""Safe orchestration from raw browser observations to page snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

from pydantic import ValidationError

from .browser import (
    BrowserObservationSource,
    BrowserUnavailableError,
    RawElementObservation,
    RawErrorObservation,
    RawFrameObservation,
    RawPageObservation,
)
from .models import (
    ElementSnapshot,
    FrameSnapshot,
    LocatorHint,
    PageSnapshot,
    ScrollResult,
    SnapshotDocument,
    SnapshotError,
    SnapshotLimits,
    SnapshotStatistics,
    SourceSnapshot,
)
from .redaction import Redactor


class CollectionFailedError(RuntimeError):
    """Raised when a valid top-level snapshot cannot be formed."""


class SnapshotCollector:
    """Collect a raw page observation and construct its redacted snapshot."""

    def __init__(
        self,
        *,
        source: BrowserObservationSource,
        redactor: Redactor | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._source = source
        self._redactor = redactor or Redactor()
        self._monotonic_clock = monotonic_clock
        self._uuid_factory = uuid_factory

    def collect(self, url: str, limits: SnapshotLimits) -> SnapshotDocument:
        """Return a validated snapshot after redacting every persisted string value."""
        started_at = datetime.now(UTC)
        started_tick = self._monotonic_clock()
        deadline = started_tick + (limits.total_timeout_ms / 1_000)
        if started_tick >= deadline:
            raise CollectionFailedError("Collection deadline was reached before navigation.")

        try:
            raw_page = self._source.collect(url, limits)
        except BrowserUnavailableError as exc:
            raise CollectionFailedError("Browser observation source is unavailable.") from exc
        except Exception as exc:
            raise CollectionFailedError("Page navigation or observation failed.") from exc

        if self._monotonic_clock() >= deadline:
            raise CollectionFailedError("Collection deadline was reached during navigation.")

        root = _find_valid_root(raw_page)
        if root is None:
            raise CollectionFailedError("No valid root frame was available for the snapshot.")

        sanitizer = _Sanitizer(self._redactor)
        page_errors = [_snapshot_error(error, sanitizer) for error in raw_page.errors]
        frames: list[FrameSnapshot] = []
        errors = list(page_errors)
        for raw_frame in sorted(raw_page.frames, key=lambda frame: frame.traversal_index):
            redaction_count_before_frame = sanitizer.count
            try:
                frame, frame_errors = _frame_snapshot(raw_frame, sanitizer)
            except (ValidationError, ValueError) as exc:
                sanitizer.count = redaction_count_before_frame
                if raw_frame is root:
                    raise CollectionFailedError(
                        "The root frame could not be modeled as a snapshot."
                    ) from exc
                frame, frame_errors = _failed_frame_snapshot(
                    raw_frame,
                    sanitizer,
                    redaction_count_before_frame,
                )
            frames.append(frame)
            errors.extend(frame_errors)

        truncated = any(frame.truncated for frame in frames)
        partial = bool(errors) or truncated
        completed_at = datetime.now(UTC)
        duration_ms = max(0, int((self._monotonic_clock() - started_tick) * 1_000))
        source = SourceSnapshot(
            requested_url=sanitizer.url(url),
            final_url=sanitizer.url(raw_page.final_url),
            title=sanitizer.text(raw_page.title),
        )
        page = PageSnapshot(
            main_frame_id=sanitizer.text(root.frame_id),
            viewport_width=raw_page.viewport_width,
            viewport_height=raw_page.viewport_height,
            language=_optional_text(raw_page.language, sanitizer),
        )
        try:
            return SnapshotDocument(
                snapshot_id=self._uuid_factory(),
                status="partial" if partial else "completed",
                started_at=started_at,
                completed_at=completed_at,
                source=source,
                limits=limits,
                statistics=SnapshotStatistics(
                    frame_count=len(frames),
                    completed_frame_count=sum(frame.status == "completed" for frame in frames),
                    failed_frame_count=sum(frame.status == "failed" for frame in frames),
                    element_count=sum(len(frame.elements) for frame in frames),
                    scroll_container_count=sum(len(frame.scroll_results) for frame in frames),
                    redaction_count=sanitizer.count,
                    duration_ms=duration_ms,
                ),
                page=page,
                frames=frames,
                errors=errors,
                truncated=truncated,
            )
        except ValidationError as exc:
            raise CollectionFailedError(
                "A valid top-level snapshot could not be formed."
            ) from exc


def _find_valid_root(raw_page: RawPageObservation) -> RawFrameObservation | None:
    roots = [frame for frame in raw_page.frames if frame.parent_frame_id is None]
    if not roots:
        return None
    root = min(roots, key=lambda frame: frame.traversal_index)
    return root if root.status != "failed" else None


def _frame_snapshot(
    raw_frame: RawFrameObservation,
    sanitizer: _Sanitizer,
) -> tuple[FrameSnapshot, list[SnapshotError]]:
    redaction_count_before_frame = sanitizer.count
    errors = [_snapshot_error(error, sanitizer) for error in raw_frame.errors]
    if raw_frame.status != "completed" and not errors:
        errors.append(
            SnapshotError(
                scope="frame",
                error_code="incomplete_frame",
                message="Frame collection did not complete.",
                recoverable=True,
                occurred_at=datetime.now(UTC),
            )
        )

    elements = [
        _element_snapshot(raw_frame.frame_id, raw_element, sanitizer)
        for raw_element in sorted(
            raw_frame.elements, key=lambda element: element.traversal_index
        )
    ]
    scroll_results = [
        ScrollResult(
            container_id=sanitizer.text(result.container_id),
            label=sanitizer.text(result.label),
            rounds=result.rounds,
            discovered_elements=result.discovered_elements,
            restored=result.restored,
            truncated=result.truncated,
            stop_reason=result.stop_reason,
        )
        for result in raw_frame.scroll_results
    ]
    return (
        FrameSnapshot(
            frame_id=sanitizer.text(raw_frame.frame_id),
            parent_frame_id=_optional_text(raw_frame.parent_frame_id, sanitizer),
            traversal_index=raw_frame.traversal_index,
            depth=raw_frame.depth,
            name=sanitizer.text(raw_frame.name),
            url=sanitizer.url(raw_frame.url),
            status=raw_frame.status,
            text_summary=sanitizer.text(raw_frame.text_summary),
            elements=elements,
            scroll_results=scroll_results,
            errors=errors,
            truncated=raw_frame.truncated,
            stop_reason=_optional_text(raw_frame.stop_reason, sanitizer),
            redaction_count=sanitizer.count - redaction_count_before_frame,
        ),
        errors,
    )


def _failed_frame_snapshot(
    raw_frame: RawFrameObservation,
    sanitizer: _Sanitizer,
    redaction_count_before_frame: int,
) -> tuple[FrameSnapshot, list[SnapshotError]]:
    error = SnapshotError(
        scope="frame",
        error_code="frame_modeling_failed",
        message="Frame observation could not be converted into a snapshot.",
        recoverable=True,
        occurred_at=datetime.now(UTC),
    )
    frame = FrameSnapshot(
        frame_id=sanitizer.text(raw_frame.frame_id),
        parent_frame_id=_optional_text(raw_frame.parent_frame_id, sanitizer),
        traversal_index=max(raw_frame.traversal_index, 0),
        depth=max(raw_frame.depth, 0),
        name=sanitizer.text(raw_frame.name),
        url=sanitizer.url(raw_frame.url),
        status="failed",
        text_summary="",
        elements=[],
        scroll_results=[],
        errors=[error],
        truncated=False,
        stop_reason="error",
        redaction_count=sanitizer.count - redaction_count_before_frame,
    )
    return frame, [error]


def _element_snapshot(
    frame_id: str,
    raw_element: RawElementObservation,
    sanitizer: _Sanitizer,
) -> ElementSnapshot:
    attributes = sanitizer.mapping(raw_element.attributes)
    return ElementSnapshot(
        element_id=f"{sanitizer.text(frame_id)}-element-{raw_element.traversal_index}",
        frame_id=sanitizer.text(frame_id),
        traversal_index=raw_element.traversal_index,
        tag=sanitizer.text(raw_element.tag),
        role=_optional_text(raw_element.role, sanitizer),
        accessible_name=_optional_text(raw_element.accessible_name, sanitizer),
        text=_optional_text(raw_element.text, sanitizer),
        attributes=attributes,
        visible=raw_element.visible,
        enabled=raw_element.enabled,
        checked=raw_element.checked,
        selected=raw_element.selected,
        expanded=raw_element.expanded,
        bounds=raw_element.bounds,
        locator_hints=[
            LocatorHint(
                strategy=hint.strategy,
                value=sanitizer.text(hint.value),
            )
            for hint in raw_element.locator_hints
        ],
    )


def _snapshot_error(raw_error: RawErrorObservation, sanitizer: _Sanitizer) -> SnapshotError:
    return SnapshotError(
        scope=sanitizer.text(raw_error.scope),
        error_code=sanitizer.text(raw_error.error_code),
        message=sanitizer.error(raw_error.message),
        recoverable=raw_error.recoverable,
        occurred_at=raw_error.occurred_at,
    )


def _optional_text(value: str | None, sanitizer: _Sanitizer) -> str | None:
    return sanitizer.text(value) if value is not None else None


class _Sanitizer:
    """Accumulate redaction counts while converting raw values to model values."""

    def __init__(self, redactor: Redactor) -> None:
        self._redactor = redactor
        self.count = 0

    def text(self, value: str) -> str:
        result = self._redactor.redact_text(value)
        self.count += result.count
        return result.value

    def error(self, value: str) -> str:
        result = self._redactor.redact_error(value)
        self.count += result.count
        return result.value

    def url(self, value: str) -> str:
        result = self._redactor.redact_url(value)
        self.count += result.count
        return result.value

    def mapping(self, value: dict[str, str]) -> dict[str, str]:
        redacted, summary = self._redactor.redact_mapping(value)
        self.count += summary.count
        return redacted
