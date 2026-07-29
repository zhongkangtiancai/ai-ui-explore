"""Bounded scrolling for document and visible nested containers."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from time import monotonic
from typing import Literal, TypedDict, cast

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ai_ui_explorer.snapshot.browser import (
    _OBSERVATION_ATTRIBUTE,
    _OBSERVATION_SELECTOR,
    RawElementObservation,
    RawScrollResult,
    _DeadlineReached,
    _element_from_payload,
    _RawFramePayload,
    _remaining_milliseconds,
)
from ai_ui_explorer.snapshot.models import SnapshotLimits

_SCROLL_ATTRIBUTE = "data-snapshot-scroll"
_SCROLL_SELECTOR = "snapshot_scroll"
_SCROLL_SELECTOR_ENGINE = """
(() => {
const containers = new Map();
const documentFor = (root) =>
  root.nodeType === Node.DOCUMENT_NODE ? root : root.ownerDocument;
const carrierFor = (root, payload) => {
  const carrier = documentFor(root).createElement("meta");
  carrier.setAttribute("data-snapshot-scroll", JSON.stringify(payload));
  return carrier;
};
const metricsFor = (element) => ({
  connected: element.isConnected,
  scrollTop: element.scrollTop,
  clientHeight: element.clientHeight,
  scrollHeight: element.scrollHeight,
});
const visibleScrollable = (element) => {
  const bounds = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  const overflowPermitsScroll = ["auto", "scroll", "overlay"].includes(style.overflowY)
    || ["auto", "scroll", "overlay"].includes(style.overflow);
  return bounds.width > 0
    && bounds.height > 0
    && style.display !== "none"
    && style.visibility !== "hidden"
    && overflowPermitsScroll
    && element.scrollHeight > element.clientHeight + 1;
};
const discover = (root, request) => {
  const documentNode = documentFor(root);
  const documentContainer = documentNode.scrollingElement || documentNode.documentElement;
  const nested = Array.from(documentNode.querySelectorAll("*"))
    .filter((element) => element !== documentContainer && visibleScrollable(element));
  const discovered = [documentContainer, ...nested].slice(0, request.limit);
  return discovered.map((element, index) => {
    const containerId = `frame-${request.frameIndex}-scroll-${index}`;
    containers.set(containerId, element);
    return {
      containerId,
      label: index === 0 ? "document" : (element.id || `container-${index}`),
      discoveryIndex: index,
      ...metricsFor(element),
    };
  });
};
const act = (request) => {
  const element = containers.get(request.containerId);
  if (!element || !element.isConnected) {
    return { connected: false };
  }
  if (request.operation === "scroll") {
    element.scrollTop = Math.min(
      element.scrollTop + request.delta,
      Math.max(element.scrollHeight - element.clientHeight, 0),
    );
  } else if (request.operation === "restore") {
    element.scrollTop = request.scrollTop;
  }
  return metricsFor(element);
};
const query = (root, selector) => {
  const request = JSON.parse(selector);
  const payload = request.operation === "discover"
    ? { containers: discover(root, request) }
    : act(request);
  return carrierFor(root, payload);
};
return {
  query,
  queryAll(root, selector) {
    return [query(root, selector)];
  },
};
})()
"""


@dataclass(frozen=True, slots=True)
class ScrollContainer:
    """A stable reference to a discovered scroll container."""

    container_id: str
    label: str
    discovery_index: int
    original_scroll_top: float
    client_height: float
    scroll_height: float


class _ContainerPayload(TypedDict):
    containerId: str
    label: str
    discoveryIndex: int
    connected: bool
    scrollTop: float
    clientHeight: float
    scrollHeight: float


class _DiscoveryPayload(TypedDict):
    containers: list[_ContainerPayload]


class _MetricsPayload(TypedDict, total=False):
    connected: bool
    scrollTop: float
    clientHeight: float
    scrollHeight: float


def discover_scroll_containers(frame: Frame, limit: int) -> list[ScrollContainer]:
    """Discover scroll containers up to the configured per-frame limit."""
    if limit <= 0:
        return []
    payload = cast(
        _DiscoveryPayload,
        _carrier_request(
            frame,
            {
                "operation": "discover",
                "limit": limit,
                "frameIndex": _frame_traversal_index(frame),
            },
        ),
    )
    return [
        ScrollContainer(
            container_id=item["containerId"],
            label=item["label"],
            discovery_index=item["discoveryIndex"],
            original_scroll_top=item["scrollTop"],
            client_height=item["clientHeight"],
            scroll_height=item["scrollHeight"],
        )
        for item in payload["containers"]
    ]


def scroll_container(
    frame: Frame,
    container: ScrollContainer,
    max_rounds: int,
    deadline: float,
) -> RawScrollResult:
    """Scroll one container within the supplied round and deadline budgets."""
    result, _ = _scroll_container_with_observations(
        frame=frame,
        container=container,
        max_rounds=max_rounds,
        deadline=deadline,
        known_signatures=set(),
        known_stable_keys=set(),
        max_elements=5_000,
        max_text_chars=500,
    )
    return result


def collect_with_scrolling(
    frame: Frame,
    limits: SnapshotLimits,
    deadline: float,
) -> tuple[list[RawElementObservation], list[RawScrollResult]]:
    """Collect initial and newly revealed interactive elements."""
    _raise_deadline(deadline)
    frame.page.set_default_timeout(_remaining_milliseconds(deadline))
    initial = _collect_elements(
        frame,
        max_elements=limits.max_elements,
        max_text_chars=limits.max_text_chars,
        deadline=deadline,
    )
    elements = [
        replace(element, traversal_index=index)
        for index, element in enumerate(initial)
    ]
    frame_id = f"frame-{_frame_traversal_index(frame)}"
    known_signatures = {_element_signature(frame_id, element) for element in elements}
    known_stable_keys = {_element_stable_key(frame_id, element) for element in elements}
    scroll_results: list[RawScrollResult] = []

    try:
        containers = discover_scroll_containers(
            frame,
            limits.max_scroll_containers_per_frame,
        )
    except (_DeadlineReached, PlaywrightTimeoutError):
        return elements, [
            _empty_result(
                container_id=f"{frame_id}-scroll-0",
                label="document",
                stop_reason="deadline",
                truncated=True,
            )
        ]
    except PlaywrightError:
        return elements, [
            _empty_result(
                container_id=f"{frame_id}-scroll-0",
                label="document",
                stop_reason="error",
                truncated=False,
            )
        ]

    for container in containers:
        result, discovered = _scroll_container_with_observations(
            frame=frame,
            container=container,
            max_rounds=limits.max_scroll_rounds_per_container,
            deadline=deadline,
            known_signatures=known_signatures,
            known_stable_keys=known_stable_keys,
            max_elements=limits.max_elements,
            max_text_chars=limits.max_text_chars,
        )
        for element in discovered:
            if len(elements) >= limits.max_elements:
                break
            elements.append(replace(element, traversal_index=len(elements)))
        scroll_results.append(result)
        if result.stop_reason == "deadline":
            break
    return elements, scroll_results


def _scroll_container_with_observations(
    *,
    frame: Frame,
    container: ScrollContainer,
    max_rounds: int,
    deadline: float,
    known_signatures: set[tuple[object, ...]],
    known_stable_keys: set[tuple[object, ...]],
    max_elements: int,
    max_text_chars: int,
) -> tuple[RawScrollResult, list[RawElementObservation]]:
    rounds = 0
    stable_rounds = 0
    previous_height = container.scroll_height
    discovered: list[RawElementObservation] = []
    stop_reason: Literal[
        "stable",
        "end_reached",
        "round_limit",
        "deadline",
        "detached",
        "error",
    ] = "round_limit"
    truncated = max_rounds == 0
    restored = False
    frame_id = f"frame-{_frame_traversal_index(frame)}"

    try:
        frame.page.wait_for_timeout(min(100, _remaining_milliseconds(deadline)))
        baseline_elements = _collect_elements(
            frame,
            max_elements=max_elements,
            max_text_chars=max_text_chars,
            deadline=deadline,
        )
        known_signatures.update(
            _element_signature(frame_id, element)
            for element in baseline_elements
        )
        known_stable_keys.update(
            _element_stable_key(frame_id, element)
            for element in baseline_elements
        )
        for _ in range(max_rounds):
            _raise_deadline(deadline)
            metrics = cast(
                _MetricsPayload,
                _carrier_request(
                    frame,
                    {
                        "operation": "scroll",
                        "containerId": container.container_id,
                        "delta": max(container.client_height * 0.8, 1),
                    },
                    deadline=deadline,
                ),
            )
            if not metrics.get("connected", False):
                stop_reason = "detached"
                break
            rounds += 1
            frame.page.wait_for_timeout(min(100, _remaining_milliseconds(deadline)))
            current_elements = _collect_elements(
                frame,
                max_elements=max_elements,
                max_text_chars=max_text_chars,
                deadline=deadline,
            )
            current_metrics = cast(
                _MetricsPayload,
                _carrier_request(
                    frame,
                    {
                        "operation": "inspect",
                        "containerId": container.container_id,
                    },
                    deadline=deadline,
                ),
            )
            if not current_metrics.get("connected", False):
                stop_reason = "detached"
                break

            new_count = 0
            for element in current_elements:
                signature = _element_signature(frame_id, element)
                stable_key = _element_stable_key(frame_id, element)
                if signature in known_signatures or stable_key in known_stable_keys:
                    known_signatures.add(signature)
                    continue
                known_signatures.add(signature)
                known_stable_keys.add(stable_key)
                discovered.append(element)
                new_count += 1

            current_height = current_metrics.get("scrollHeight", previous_height)
            if new_count == 0 and abs(current_height - previous_height) <= 1:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_height = current_height
            if stable_rounds >= 2:
                stop_reason = "stable"
                break
        else:
            stop_reason = "round_limit"
            truncated = True
    except (_DeadlineReached, PlaywrightTimeoutError):
        stop_reason = "deadline"
        truncated = True
    except PlaywrightError as exc:
        stop_reason = "detached" if "detached" in str(exc).lower() else "error"
    finally:
        try:
            restore_metrics = cast(
                _MetricsPayload,
                _carrier_request(
                    frame,
                    {
                        "operation": "restore",
                        "containerId": container.container_id,
                        "scrollTop": container.original_scroll_top,
                    },
                    timeout_ms=250,
                ),
            )
            restored = (
                restore_metrics.get("connected", False)
                and abs(
                    restore_metrics.get("scrollTop", container.original_scroll_top + 2)
                    - container.original_scroll_top
                )
                <= 1
            )
        except PlaywrightError:
            restored = False

    return (
        RawScrollResult(
            container_id=container.container_id,
            label=container.label,
            rounds=rounds,
            discovered_elements=len(discovered),
            restored=restored,
            truncated=truncated,
            stop_reason=stop_reason,
        ),
        discovered,
    )


def _collect_elements(
    frame: Frame,
    *,
    max_elements: int,
    max_text_chars: int,
    deadline: float,
) -> list[RawElementObservation]:
    selector_argument = json.dumps(
        {
            "maxElements": max_elements,
            "maxTextChars": max_text_chars,
        },
        separators=(",", ":"),
    )
    raw_payload = frame.locator(
        f"{_OBSERVATION_SELECTOR}={selector_argument}"
    ).get_attribute(
        _OBSERVATION_ATTRIBUTE,
        timeout=_remaining_milliseconds(deadline),
    )
    if raw_payload is None:
        raise PlaywrightError("Utility-world observation carrier has no payload.")
    frame_payload = cast(_RawFramePayload, json.loads(raw_payload))
    return [
        _element_from_payload(payload, index)
        for index, payload in enumerate(frame_payload["elements"]["observations"])
    ]


def _carrier_request(
    frame: Frame,
    request: dict[str, object],
    *,
    deadline: float | None = None,
    timeout_ms: int | None = None,
) -> object:
    selector_argument = json.dumps(request, separators=(",", ":"))
    timeout = (
        timeout_ms
        if timeout_ms is not None
        else (_remaining_milliseconds(deadline) if deadline is not None else None)
    )
    locator = frame.locator(f"{_SCROLL_SELECTOR}={selector_argument}")
    raw_payload = (
        locator.get_attribute(_SCROLL_ATTRIBUTE, timeout=timeout)
        if timeout is not None
        else locator.get_attribute(_SCROLL_ATTRIBUTE)
    )
    if raw_payload is None:
        raise PlaywrightError("Utility-world scroll carrier has no payload.")
    return json.loads(raw_payload)


def _frame_traversal_index(frame: Frame) -> int:
    ordered: list[Frame] = []

    def visit(current: Frame) -> None:
        ordered.append(current)
        for child in current.child_frames:
            visit(child)

    visit(frame.page.main_frame)
    for index, current in enumerate(ordered):
        if current == frame:
            return index
    raise PlaywrightError("Frame detached before scroll traversal.")


def _element_signature(
    frame_id: str,
    element: RawElementObservation,
) -> tuple[object, ...]:
    bounds = element.bounds
    rounded_bounds = (
        None
        if bounds is None
        else (
            round(bounds.x),
            round(bounds.y),
            round(bounds.width),
            round(bounds.height),
        )
    )
    return (*_element_stable_key(frame_id, element), rounded_bounds)


def _element_stable_key(
    frame_id: str,
    element: RawElementObservation,
) -> tuple[object, ...]:
    return (
        frame_id,
        element.tag,
        element.role,
        element.accessible_name,
        tuple(sorted(element.attributes.items())),
    )


def _raise_deadline(deadline: float) -> None:
    if monotonic() >= deadline:
        raise _DeadlineReached


def _empty_result(
    *,
    container_id: str,
    label: str,
    stop_reason: Literal["deadline", "error"],
    truncated: bool,
) -> RawScrollResult:
    return RawScrollResult(
        container_id=container_id,
        label=label,
        rounds=0,
        discovered_elements=0,
        restored=False,
        truncated=truncated,
        stop_reason=stop_reason,
    )
