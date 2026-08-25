"""Safe orchestration from raw browser observations to page snapshots."""

from __future__ import annotations

import hashlib
import json
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
    RawLocatorCandidate,
    RawPageObservation,
)
from .models import (
    ElementSnapshot,
    FrameSnapshot,
    LocatorParameter,
    LocatorStrategy,
    PageSnapshot,
    ScrollResult,
    SnapshotDocument,
    SnapshotError,
    SnapshotLimits,
    SnapshotLocatorCandidate,
    SnapshotStatistics,
    SourceSnapshot,
)
from .redaction import Redactor


class CollectionFailedError(RuntimeError):
    """Raised when a valid top-level snapshot cannot be formed."""


_LOCATOR_PARAMETER_KEYS: dict[LocatorStrategy, frozenset[str]] = {
    "role": frozenset({"role", "name", "exact"}),
    "label": frozenset({"value", "exact"}),
    "text": frozenset({"value", "exact"}),
    "placeholder": frozenset({"value", "exact"}),
    "alt": frozenset({"value", "exact"}),
    "title": frozenset({"value", "exact"}),
    "testid": frozenset({"value"}),
    "id": frozenset({"value"}),
    "name": frozenset({"value"}),
    "aria": frozenset({"attribute", "value"}),
    "css": frozenset({"selector"}),
    "xpath": frozenset({"expression"}),
    "position": frozenset(
        {
            "x",
            "y",
            "width",
            "height",
            "viewportWidth",
            "viewportHeight",
        }
    ),
}


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

    def is_bound_to_source(self, source: BrowserObservationSource) -> bool:
        """Check source identity without exposing the bound observation source."""
        return self._source is source

    def collect(self, url: str, limits: SnapshotLimits) -> SnapshotDocument:
        """Return a validated snapshot after redacting every persisted string value."""
        return self._collect(url=url, limits=limits, current_page=False)

    def collect_current(self, url: str, limits: SnapshotLimits) -> SnapshotDocument:
        """Snapshot a task-bound current page without triggering navigation."""
        return self._collect(url=url, limits=limits, current_page=True)

    def _collect(
        self,
        *,
        url: str,
        limits: SnapshotLimits,
        current_page: bool,
    ) -> SnapshotDocument:
        """Build one redacted snapshot from either a URL or the current page."""
        started_at = datetime.now(UTC)
        started_tick = self._monotonic_clock()
        deadline = started_tick + (limits.total_timeout_ms / 1_000)
        if self._monotonic_clock() >= deadline:
            raise CollectionFailedError("Collection deadline was reached before navigation.")

        try:
            if current_page:
                raw_page = self._source.collect_current(limits)  # type: ignore[attr-defined]
            else:
                raw_page = self._source.collect(url, limits)
        except BrowserUnavailableError as exc:
            raise CollectionFailedError("Browser observation source is unavailable.") from exc
        except Exception as exc:
            raise CollectionFailedError("Page navigation or observation failed.") from exc

        root = _find_valid_root(raw_page)
        if root is None:
            raise CollectionFailedError("No valid root frame was available for the snapshot.")

        try:
            return self._build_snapshot(
                url=url,
                limits=limits,
                raw_page=raw_page,
                root=root,
                started_at=started_at,
                started_tick=started_tick,
            )
        except CollectionFailedError:
            raise
        except (ValidationError, ValueError) as exc:
            raise CollectionFailedError(
                "A valid top-level snapshot could not be formed."
            ) from exc

    def _build_snapshot(
        self,
        *,
        url: str,
        limits: SnapshotLimits,
        raw_page: RawPageObservation,
        root: RawFrameObservation,
        started_at: datetime,
        started_tick: float,
    ) -> SnapshotDocument:
        sanitizer = _Sanitizer(self._redactor)
        page_errors = [_snapshot_error(error, sanitizer) for error in raw_page.errors]
        frames: list[FrameSnapshot] = []
        locator_candidates: list[SnapshotLocatorCandidate] = []
        errors = list(page_errors)
        for raw_frame in sorted(raw_page.frames, key=lambda frame: frame.traversal_index):
            checkpoint = sanitizer.checkpoint()
            try:
                frame, frame_errors, frame_locator_candidates = _frame_snapshot(
                    raw_frame,
                    sanitizer,
                )
            except (ValidationError, ValueError) as exc:
                sanitizer.restore(checkpoint)
                if raw_frame is root:
                    raise CollectionFailedError(
                        "The root frame could not be modeled as a snapshot."
                    ) from exc
                frame, frame_errors = _failed_frame_snapshot(
                    raw_frame,
                    sanitizer,
                    checkpoint,
                )
                frame_locator_candidates = []
            frames.append(frame)
            locator_candidates.extend(frame_locator_candidates)
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
                redaction_categories=sorted(sanitizer.categories),
                locator_candidate_count=len(locator_candidates),
                duration_ms=duration_ms,
            ),
            page=page,
            frames=frames,
            locator_candidates=locator_candidates,
            errors=errors,
            truncated=truncated,
        )


def _find_valid_root(raw_page: RawPageObservation) -> RawFrameObservation | None:
    roots = [frame for frame in raw_page.frames if frame.parent_frame_id is None]
    if not roots:
        return None
    root = min(roots, key=lambda frame: frame.traversal_index)
    return root if root.status != "failed" else None


def _frame_snapshot(
    raw_frame: RawFrameObservation,
    sanitizer: _Sanitizer,
) -> tuple[
    FrameSnapshot,
    list[SnapshotError],
    list[SnapshotLocatorCandidate],
]:
    checkpoint = sanitizer.checkpoint()
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

    elements: list[ElementSnapshot] = []
    locator_candidates: list[SnapshotLocatorCandidate] = []
    for raw_element in sorted(
        raw_frame.elements,
        key=lambda element: element.traversal_index,
    ):
        element = _element_snapshot(raw_frame.frame_id, raw_element, sanitizer)
        elements.append(element)
        locator_candidates.extend(
            _locator_candidates(
                frame_id=element.frame_id,
                element_id=element.element_id,
                raw_candidates=raw_element.locator_candidates,
                sanitizer=sanitizer,
            )
        )
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
            stop_reason=raw_frame.stop_reason,
            redaction_count=sanitizer.count - checkpoint[0],
            redaction_categories=sorted(sanitizer.categories_since(checkpoint)),
        ),
        errors,
        locator_candidates,
    )


def _failed_frame_snapshot(
    raw_frame: RawFrameObservation,
    sanitizer: _Sanitizer,
    checkpoint: tuple[int, int],
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
        redaction_count=sanitizer.count - checkpoint[0],
        redaction_categories=sorted(sanitizer.categories_since(checkpoint)),
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
        href=_optional_url(raw_element.href, sanitizer),
        attributes=attributes,
        visible=raw_element.visible,
        enabled=raw_element.enabled,
        checked=raw_element.checked,
        selected=raw_element.selected,
        expanded=raw_element.expanded,
        bounds=raw_element.bounds,
    )


def _locator_candidates(
    *,
    frame_id: str,
    element_id: str,
    raw_candidates: tuple[RawLocatorCandidate, ...],
    sanitizer: _Sanitizer,
) -> list[SnapshotLocatorCandidate]:
    mapped: list[SnapshotLocatorCandidate] = []
    for raw in raw_candidates:
        if not raw.parameters.keys() <= _LOCATOR_PARAMETER_KEYS[raw.strategy]:
            raise ValueError("locator candidate contains unsupported parameter keys")
        parameters = {
            key: (
                _locator_string_parameter(key, value, sanitizer)
                if isinstance(value, str)
                else value
            )
            for key, value in raw.parameters.items()
        }
        limitations = [sanitizer.text(value) for value in raw.limitations]
        mapped.append(
            SnapshotLocatorCandidate(
                locator_id=_stable_locator_id(
                    frame_id,
                    element_id,
                    raw.strategy,
                    parameters,
                    raw.rank,
                ),
                element_ref=element_id,
                frame_ref=frame_id,
                strategy=raw.strategy,
                parameters=parameters,
                source=raw.source,
                uniqueness=raw.uniqueness,
                match_count=raw.match_count,
                stability=raw.stability,
                confidence=raw.confidence,
                rank=raw.rank,
                recommended=raw.recommended,
                limitations=limitations,
            )
        )
    return mapped


def _locator_string_parameter(
    key: str,
    value: str,
    sanitizer: _Sanitizer,
) -> str:
    return sanitizer.mapping({key: value})[key]


def _stable_locator_id(
    frame_id: str,
    element_id: str,
    strategy: LocatorStrategy,
    parameters: dict[str, LocatorParameter],
    rank: int,
) -> str:
    canonical = json.dumps(
        [frame_id, element_id, strategy, parameters, rank],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"locator-{strategy}-{digest[:20]}"


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


def _optional_url(value: str | None, sanitizer: _Sanitizer) -> str | None:
    return sanitizer.url(value) if value is not None else None


class _Sanitizer:
    """Accumulate redaction counts while converting raw values to model values."""

    def __init__(self, redactor: Redactor) -> None:
        self._redactor = redactor
        self.count = 0
        self._category_events: list[frozenset[str]] = []

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(
            category
            for event in self._category_events
            for category in event
        )

    def checkpoint(self) -> tuple[int, int]:
        return self.count, len(self._category_events)

    def restore(self, checkpoint: tuple[int, int]) -> None:
        self.count = checkpoint[0]
        del self._category_events[checkpoint[1]:]

    def categories_since(self, checkpoint: tuple[int, int]) -> frozenset[str]:
        return frozenset(
            category
            for event in self._category_events[checkpoint[1]:]
            for category in event
        )

    def _record(self, count: int, categories: frozenset[str]) -> None:
        self.count += count
        if categories:
            self._category_events.append(categories)

    def text(self, value: str) -> str:
        result = self._redactor.redact_text(value)
        self._record(result.count, result.categories)
        return result.value

    def error(self, value: str) -> str:
        result = self._redactor.redact_error(value)
        self._record(result.count, result.categories)
        return result.value

    def url(self, value: str) -> str:
        result = self._redactor.redact_url(value)
        self._record(result.count, result.categories)
        return result.value

    def mapping(self, value: dict[str, str]) -> dict[str, str]:
        redacted, summary = self._redactor.redact_mapping(value)
        self._record(summary.count, summary.categories)
        return redacted
