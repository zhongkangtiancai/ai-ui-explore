"""Playwright-backed raw page observation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Literal, Protocol, TypedDict, cast

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Page, sync_playwright

from ai_ui_explorer.snapshot.models import Bounds, SnapshotLimits

_INTERACTIVE_ELEMENT_SCRIPT = """
({ maxElements, maxTextChars }) => {
  const clip = (value) => {
    if (typeof value !== "string") return null;
    return value.replace(/\\s+/g, " ").trim().slice(0, maxTextChars);
  };
  const implicitRole = (element) => {
    const tag = element.tagName.toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && element.hasAttribute("href")) return "link";
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (tag === "summary") return "button";
    if (tag === "input") {
      const type = (element.getAttribute("type") || "text").toLowerCase();
      if (["button", "reset", "submit"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      return "textbox";
    }
    return null;
  };
  const labelText = (element) => {
    const labels = Array.from(element.labels || []);
    return clip(labels.map((label) => label.innerText || "").join(" "));
  };
  const referencedName = (element) => {
    const ids = (element.getAttribute("aria-labelledby") || "").split(/\\s+/).filter(Boolean);
    return clip(ids.map((id) => document.getElementById(id)?.innerText || "").join(" "));
  };
  const stateFromAria = (element, attribute) => {
    const value = element.getAttribute(attribute);
    if (value === "true") return true;
    if (value === "false") return false;
    return null;
  };
  const candidates = document.querySelectorAll(
    "a[href],button,input:not([type='hidden']),select,textarea,summary,[role],[tabindex]"
  );
  const observations = [];
  for (const element of candidates) {
    const bounds = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    const visible = bounds.width > 0 && bounds.height > 0
      && style.display !== "none"
      && style.visibility !== "hidden";
    if (!visible) continue;

    const tag = element.tagName.toLowerCase();
    const role = element.getAttribute("role") || implicitRole(element);
    const label = labelText(element);
    const accessibleName = clip(element.getAttribute("aria-label"))
      || referencedName(element)
      || label
      || clip(element.getAttribute("alt"))
      || clip(element.innerText)
      || clip(element.getAttribute("title"))
      || clip(element.getAttribute("placeholder"));
    const attributes = {};
    for (const attribute of element.attributes) {
      const name = attribute.name.toLowerCase();
      if (
        ["id", "name", "type", "placeholder", "data-testid"].includes(name)
        || name.startsWith("aria-")
      ) {
        attributes[name] = clip(element.getAttribute(name)) || "";
      }
    }

    let enabled = null;
    if (["a", "button", "input", "select", "textarea", "option"].includes(tag)) {
      enabled = !element.disabled;
    }
    const inputType = (element.getAttribute("type") || "").toLowerCase();
    let checked = null;
    if (
      (tag === "input" && ["checkbox", "radio"].includes(inputType))
      || ["checkbox", "radio", "switch"].includes(role)
    ) {
      checked = typeof element.checked === "boolean"
        ? element.checked
        : stateFromAria(element, "aria-checked");
    }
    let selected = null;
    if (tag === "option") selected = element.selected;
    else if (element.hasAttribute("aria-selected")) {
      selected = stateFromAria(element, "aria-selected");
    }

    const locatorHints = [];
    if (role && accessibleName) {
      locatorHints.push({ strategy: "role", value: clip(`${role}:${accessibleName}`) || role });
    }
    if (label) locatorHints.push({ strategy: "label", value: label });
    if (attributes["data-testid"]) {
      locatorHints.push({ strategy: "testid", value: attributes["data-testid"] });
    }
    if (attributes.id) locatorHints.push({ strategy: "id", value: attributes.id });

    observations.push({
      tag,
      role,
      accessibleName,
      text: clip(element.innerText),
      attributes,
      visible,
      enabled,
      checked,
      selected,
      expanded: stateFromAria(element, "aria-expanded"),
      bounds: {
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
      },
      locatorHints,
    });
    if (observations.length >= maxElements) break;
  }
  return observations;
}
"""

_BODY_TEXT_SCRIPT = """
(maxTextChars) => {
  const text = document.body?.innerText || "";
  return text.slice(0, maxTextChars);
}
"""


@dataclass(frozen=True, slots=True)
class RawLocatorHint:
    strategy: Literal["role", "label", "testid", "id"]
    value: str


@dataclass(frozen=True, slots=True)
class RawElementObservation:
    traversal_index: int
    tag: str
    role: str | None
    accessible_name: str | None
    text: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: Bounds | None
    locator_hints: tuple[RawLocatorHint, ...]


@dataclass(frozen=True, slots=True)
class RawErrorObservation:
    scope: str
    error_code: str
    message: str
    recoverable: bool
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RawScrollResult:
    container_id: str
    label: str
    rounds: int
    discovered_elements: int
    restored: bool
    truncated: bool
    stop_reason: Literal[
        "stable",
        "end_reached",
        "round_limit",
        "deadline",
        "detached",
        "error",
    ]


@dataclass(slots=True)
class RawFrameObservation:
    frame_id: str
    parent_frame_id: str | None
    traversal_index: int
    depth: int
    name: str
    url: str
    status: Literal["completed", "partial", "failed"]
    text_summary: str
    elements: list[RawElementObservation]
    scroll_results: list[RawScrollResult]
    errors: list[RawErrorObservation]
    truncated: bool
    stop_reason: str | None


@dataclass(slots=True)
class RawPageObservation:
    final_url: str
    title: str
    viewport_width: int
    viewport_height: int
    language: str | None
    frames: list[RawFrameObservation]
    errors: list[RawErrorObservation]
    deadline_reached: bool


class BrowserUnavailableError(RuntimeError):
    """Raised when the project-local Chromium executable is unavailable."""


class BrowserObservationSource(Protocol):
    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        """Collect an unredacted observation for later sanitization."""


class PlaywrightBrowserSource:
    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless

    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        """Collect initial visible content without navigation side effects beyond page load."""
        deadline = monotonic() + (limits.total_timeout_ms / 1_000)
        with _managed_page(headless=self._headless) as page:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=_remaining_milliseconds(deadline),
            )
            _wait_for_dynamic_frames(page, deadline)

            ordered_frames = _ordered_frames(page.main_frame)
            page_errors: list[RawErrorObservation] = []
            if len(ordered_frames) > limits.max_frames:
                ordered_frames = ordered_frames[: limits.max_frames]
                page_errors.append(
                    _raw_error(
                        scope="page",
                        error_code="max_frames_reached",
                        message="Frame collection stopped at the configured maximum.",
                    )
                )

            frame_ids = {
                id(frame): f"frame-{index}" for index, frame in enumerate(ordered_frames)
            }
            frames: list[RawFrameObservation] = []
            observed_elements = 0
            deadline_reached = False
            for traversal_index, frame in enumerate(ordered_frames):
                remaining_elements = max(limits.max_elements - observed_elements, 0)
                frame_observation = _observe_frame(
                    frame=frame,
                    frame_id=frame_ids[id(frame)],
                    frame_ids=frame_ids,
                    traversal_index=traversal_index,
                    remaining_elements=remaining_elements,
                    limits=limits,
                    deadline=deadline,
                )
                frames.append(frame_observation)
                observed_elements += len(frame_observation.elements)
                deadline_reached = deadline_reached or frame_observation.stop_reason == "deadline"

            viewport = page.viewport_size or {"width": 1280, "height": 720}
            language = cast(str | None, page.locator("html").get_attribute("lang"))
            return RawPageObservation(
                final_url=page.url,
                title=page.title(),
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                language=language,
                frames=frames,
                errors=page_errors,
                deadline_reached=deadline_reached,
            )


class _RawBoundsPayload(TypedDict):
    x: float
    y: float
    width: float
    height: float


class _RawLocatorHintPayload(TypedDict):
    strategy: Literal["role", "label", "testid", "id"]
    value: str


class _RawElementPayload(TypedDict):
    tag: str
    role: str | None
    accessibleName: str | None
    text: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: _RawBoundsPayload | None
    locatorHints: list[_RawLocatorHintPayload]


@contextmanager
def _managed_page(*, headless: bool) -> Iterator[Page]:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except PlaywrightError as exc:
            if "executable doesn't exist" in str(exc).lower():
                raise BrowserUnavailableError(
                    "Project-local Chromium is unavailable. "
                    "Run: python -m playwright install chromium"
                ) from None
            raise

        try:
            context = browser.new_context()
            try:
                page = context.new_page()
                try:
                    yield page
                finally:
                    with suppress(PlaywrightError):
                        page.close()
            finally:
                with suppress(PlaywrightError):
                    context.close()
        finally:
            with suppress(PlaywrightError):
                browser.close()


def _remaining_milliseconds(deadline: float) -> int:
    return max(1, int((deadline - monotonic()) * 1_000))


def _wait_for_dynamic_frames(page: Page, deadline: float) -> None:
    remaining = _remaining_milliseconds(deadline)
    page.wait_for_timeout(min(150, remaining))


def _ordered_frames(main_frame: Frame) -> list[Frame]:
    ordered: list[Frame] = []

    def visit(frame: Frame) -> None:
        ordered.append(frame)
        for child in frame.child_frames:
            visit(child)

    visit(main_frame)
    return ordered


def _observe_frame(
    *,
    frame: Frame,
    frame_id: str,
    frame_ids: dict[int, str],
    traversal_index: int,
    remaining_elements: int,
    limits: SnapshotLimits,
    deadline: float,
) -> RawFrameObservation:
    parent = frame.parent_frame
    parent_frame_id = frame_ids.get(id(parent)) if parent is not None else None
    depth = _frame_depth(frame)
    name = "main" if parent is None else (frame.name or frame_id)
    url = frame.url
    if monotonic() >= deadline:
        error = _raw_error(
            scope=f"frame:{frame_id}",
            error_code="deadline_reached",
            message="Frame observation stopped at the global deadline.",
        )
        return RawFrameObservation(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            traversal_index=traversal_index,
            depth=depth,
            name=name,
            url=url,
            status="failed",
            text_summary="",
            elements=[],
            scroll_results=[],
            errors=[error],
            truncated=True,
            stop_reason="deadline",
        )
    if remaining_elements == 0:
        return RawFrameObservation(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            traversal_index=traversal_index,
            depth=depth,
            name=name,
            url=url,
            status="partial",
            text_summary="",
            elements=[],
            scroll_results=[],
            errors=[],
            truncated=True,
            stop_reason="max_elements",
        )

    try:
        text_summary = cast(str, frame.evaluate(_BODY_TEXT_SCRIPT, limits.max_text_chars))
        payloads = cast(
            list[_RawElementPayload],
            frame.evaluate(
                _INTERACTIVE_ELEMENT_SCRIPT,
                {
                    "maxElements": remaining_elements,
                    "maxTextChars": limits.max_text_chars,
                },
            ),
        )
        elements = [
            _element_from_payload(payload, index) for index, payload in enumerate(payloads)
        ]
    except PlaywrightError as exc:
        error_code = (
            "frame_detached" if "detached" in str(exc).lower() else "frame_observation_failed"
        )
        error = _raw_error(
            scope=f"frame:{frame_id}",
            error_code=error_code,
            message=str(exc),
        )
        return RawFrameObservation(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            traversal_index=traversal_index,
            depth=depth,
            name=name,
            url=url,
            status="failed",
            text_summary="",
            elements=[],
            scroll_results=[],
            errors=[error],
            truncated=False,
            stop_reason="detached" if error_code == "frame_detached" else "error",
        )

    return RawFrameObservation(
        frame_id=frame_id,
        parent_frame_id=parent_frame_id,
        traversal_index=traversal_index,
        depth=depth,
        name=name,
        url=url,
        status="completed",
        text_summary=text_summary,
        elements=elements,
        scroll_results=[],
        errors=[],
        truncated=False,
        stop_reason=None,
    )


def _frame_depth(frame: Frame) -> int:
    depth = 0
    parent = frame.parent_frame
    while parent is not None:
        depth += 1
        parent = parent.parent_frame
    return depth


def _element_from_payload(
    payload: _RawElementPayload,
    traversal_index: int,
) -> RawElementObservation:
    bounds_payload = payload["bounds"]
    bounds = (
        Bounds(
            x=bounds_payload["x"],
            y=bounds_payload["y"],
            width=bounds_payload["width"],
            height=bounds_payload["height"],
        )
        if bounds_payload is not None
        else None
    )
    return RawElementObservation(
        traversal_index=traversal_index,
        tag=payload["tag"],
        role=payload["role"],
        accessible_name=payload["accessibleName"],
        text=payload["text"],
        attributes=payload["attributes"],
        visible=payload["visible"],
        enabled=payload["enabled"],
        checked=payload["checked"],
        selected=payload["selected"],
        expanded=payload["expanded"],
        bounds=bounds,
        locator_hints=tuple(
            RawLocatorHint(strategy=hint["strategy"], value=hint["value"])
            for hint in payload["locatorHints"]
        ),
    )


def _raw_error(*, scope: str, error_code: str, message: str) -> RawErrorObservation:
    return RawErrorObservation(
        scope=scope,
        error_code=error_code,
        message=message,
        recoverable=True,
        occurred_at=datetime.now(UTC),
    )
