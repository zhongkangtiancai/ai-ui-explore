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
const scopedNodeIds = new WeakMap();
let nextScopedNodeId = 0;
const scopedNodeIdFor = (element) => {
  let nodeId = scopedNodeIds.get(element);
  if (!nodeId) {
    nextScopedNodeId += 1;
    nodeId = `scoped-node-${nextScopedNodeId}`;
    scopedNodeIds.set(element, nodeId);
  }
  return nodeId;
};
const documentFor = (root) =>
  root.nodeType === Node.DOCUMENT_NODE ? root : root.ownerDocument;
const carrierFor = (root, payload) => {
  const carrier = documentFor(root).createElement("meta");
  carrier.setAttribute("data-snapshot-scroll", JSON.stringify(payload));
  return carrier;
};
const descendantNodeIdsFor = (element, maxElements) => {
  const candidates = element.querySelectorAll(
    "a[href],button,input:not([type='hidden']),select,textarea,summary,[role],[tabindex]"
  );
  const nodeIds = [];
  for (const candidate of candidates) {
    const bounds = candidate.getBoundingClientRect();
    const style = window.getComputedStyle(candidate);
    if (
      bounds.width <= 0
      || bounds.height <= 0
      || style.display === "none"
      || style.visibility === "hidden"
    ) {
      continue;
    }
    nodeIds.push(scopedNodeIdFor(candidate));
    if (nodeIds.length >= maxElements) break;
  }
  return nodeIds;
};
const metricsFor = (element, maxElements = 5000) => ({
  connected: element.isConnected,
  scrollTop: element.scrollTop,
  clientHeight: element.clientHeight,
  scrollHeight: element.scrollHeight,
  descendantNodeIds: descendantNodeIdsFor(element, maxElements),
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
  const candidates = [documentContainer, ...nested].slice(0, request.limit + 1);
  const discovered = candidates.slice(0, request.limit);
  return {
    hasMore: candidates.length > request.limit,
    containers: discovered.map((element, index) => {
      const containerId = `frame-${request.frameIndex}-scroll-${index}`;
      containers.set(containerId, element);
      return {
        containerId,
        label: index === 0 ? "document" : (element.id || `container-${index}`),
        discoveryIndex: index,
        ...metricsFor(element, request.maxElements),
      };
    }),
  };
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
  return metricsFor(element, request.maxElements);
};
const query = (root, selector) => {
  const request = JSON.parse(selector);
  const payload = request.operation === "discover"
    ? discover(root, request)
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
    hasMore: bool


class _MetricsPayload(TypedDict, total=False):
    connected: bool
    scrollTop: float
    clientHeight: float
    scrollHeight: float
    descendantNodeIds: list[str]


@dataclass(frozen=True, slots=True)
class _CollectedElement:
    node_id: str
    observation: RawElementObservation


@dataclass(frozen=True, slots=True)
class _ElementBatch:
    elements: tuple[_CollectedElement, ...]
    truncated: bool
    text_truncated: bool


@dataclass(frozen=True, slots=True)
class RawScrollingObservation:
    elements: list[RawElementObservation]
    scroll_results: list[RawScrollResult]
    text_truncated: bool
    container_limit_reached: bool


@dataclass(frozen=True, slots=True)
class _ScrollContainerDiscovery:
    containers: list[ScrollContainer]
    has_more: bool


def discover_scroll_containers(frame: Frame, limit: int) -> list[ScrollContainer]:
    """Discover scroll containers up to the configured per-frame limit."""
    return _discover_scroll_containers(frame, limit).containers


def _discover_scroll_containers(
    frame: Frame,
    limit: int,
) -> _ScrollContainerDiscovery:
    payload = cast(
        _DiscoveryPayload,
        _carrier_request(
            frame,
            {
                "operation": "discover",
                "limit": max(limit, 0),
                "frameIndex": _frame_traversal_index(frame),
            },
        ),
    )
    return _ScrollContainerDiscovery(
        containers=[
            ScrollContainer(
                container_id=item["containerId"],
                label=item["label"],
                discovery_index=item["discoveryIndex"],
                original_scroll_top=item["scrollTop"],
                client_height=item["clientHeight"],
                scroll_height=item["scrollHeight"],
            )
            for item in payload["containers"]
        ],
        has_more=payload["hasMore"],
    )


def scroll_container(
    frame: Frame,
    container: ScrollContainer,
    max_rounds: int,
    deadline: float,
) -> RawScrollResult:
    """Scroll one container within the supplied round and deadline budgets."""
    result, _, _ = _scroll_container_with_observations(
        frame=frame,
        container=container,
        max_rounds=max_rounds,
        deadline=deadline,
        known_node_ids=set(),
        remaining_elements=5_000,
        emit_baseline_new=False,
        max_elements=5_000,
        max_text_chars=500,
    )
    return result


def collect_with_scrolling(
    frame: Frame,
    limits: SnapshotLimits,
    deadline: float,
) -> RawScrollingObservation:
    """Collect initial and newly revealed interactive elements."""
    _raise_deadline(deadline)
    frame.page.set_default_timeout(_remaining_milliseconds(deadline))
    initial_batch = _collect_elements(
        frame,
        max_elements=limits.max_elements,
        max_text_chars=limits.max_text_chars,
        deadline=deadline,
    )
    elements = [
        replace(item.observation, traversal_index=index)
        for index, item in enumerate(initial_batch.elements)
    ]
    frame_id = f"frame-{_frame_traversal_index(frame)}"
    known_node_ids = {item.node_id for item in initial_batch.elements}
    scroll_results: list[RawScrollResult] = []
    remaining_elements = limits.max_elements - len(elements)
    if initial_batch.truncated or remaining_elements == 0:
        return RawScrollingObservation(
            elements=elements,
            scroll_results=[
                _empty_result(
                    container_id=f"{frame_id}-scroll-0",
                    label="document",
                    stop_reason="max_elements",
                    truncated=True,
                )
            ],
            text_truncated=initial_batch.text_truncated,
            container_limit_reached=False,
        )

    try:
        discovery = _discover_scroll_containers(
            frame,
            limits.max_scroll_containers_per_frame,
        )
    except (_DeadlineReached, PlaywrightTimeoutError):
        return RawScrollingObservation(
            elements=elements,
            scroll_results=[
                _empty_result(
                    container_id=f"{frame_id}-scroll-0",
                    label="document",
                    stop_reason="deadline",
                    truncated=True,
                )
            ],
            text_truncated=initial_batch.text_truncated,
            container_limit_reached=False,
        )
    except PlaywrightError:
        return RawScrollingObservation(
            elements=elements,
            scroll_results=[
                _empty_result(
                    container_id=f"{frame_id}-scroll-0",
                    label="document",
                    stop_reason="error",
                    truncated=False,
                )
            ],
            text_truncated=initial_batch.text_truncated,
            container_limit_reached=False,
        )

    text_truncated = initial_batch.text_truncated
    for container in discovery.containers:
        (
            result,
            discovered,
            container_text_truncated,
        ) = _scroll_container_with_observations(
            frame=frame,
            container=container,
            max_rounds=limits.max_scroll_rounds_per_container,
            deadline=deadline,
            known_node_ids=known_node_ids,
            remaining_elements=remaining_elements,
            emit_baseline_new=True,
            max_elements=limits.max_elements,
            max_text_chars=limits.max_text_chars,
        )
        for element in discovered:
            elements.append(replace(element, traversal_index=len(elements)))
        remaining_elements -= len(discovered)
        scroll_results.append(result)
        text_truncated = text_truncated or container_text_truncated
        if result.stop_reason in {"deadline", "max_elements"}:
            break
    return RawScrollingObservation(
        elements=elements,
        scroll_results=scroll_results,
        text_truncated=text_truncated,
        container_limit_reached=discovery.has_more,
    )


def _scroll_container_with_observations(
    *,
    frame: Frame,
    container: ScrollContainer,
    max_rounds: int,
    deadline: float,
    known_node_ids: set[str],
    remaining_elements: int,
    emit_baseline_new: bool,
    max_elements: int,
    max_text_chars: int,
) -> tuple[RawScrollResult, list[RawElementObservation], bool]:
    rounds = 0
    stable_rounds = 0
    previous_height = container.scroll_height
    discovered: list[RawElementObservation] = []
    stop_reason: Literal[
        "stable",
        "end_reached",
        "round_limit",
        "max_elements",
        "deadline",
        "detached",
        "error",
    ] = "round_limit"
    truncated = max_rounds == 0
    restored = False
    text_truncated = False

    try:
        frame.page.wait_for_timeout(min(100, _remaining_milliseconds(deadline)))
        baseline_metrics = cast(
            _MetricsPayload,
            _carrier_request(
                frame,
                {
                    "operation": "inspect",
                    "containerId": container.container_id,
                    "maxElements": max_elements,
                },
                deadline=deadline,
            ),
        )
        if not baseline_metrics.get("connected", False):
            stop_reason = "detached"
            return (
                _result(
                    container=container,
                    rounds=rounds,
                    discovered=discovered,
                    restored=False,
                    truncated=truncated,
                    stop_reason=stop_reason,
                ),
                discovered,
                text_truncated,
            )
        scoped_node_ids = set(baseline_metrics.get("descendantNodeIds", []))
        baseline_batch = _collect_elements(
            frame,
            max_elements=max_elements,
            max_text_chars=max_text_chars,
            deadline=deadline,
        )
        text_truncated = text_truncated or baseline_batch.text_truncated
        if emit_baseline_new:
            remaining_elements = _append_new_elements(
                baseline_batch,
                known_node_ids=known_node_ids,
                discovered=discovered,
                remaining_elements=remaining_elements,
            )
        else:
            known_node_ids.update(item.node_id for item in baseline_batch.elements)
        if remaining_elements == 0:
            stop_reason = "max_elements"
            truncated = True

        for _ in range(max_rounds):
            if stop_reason == "max_elements":
                break
            _raise_deadline(deadline)
            metrics = cast(
                _MetricsPayload,
                _carrier_request(
                    frame,
                    {
                        "operation": "scroll",
                        "containerId": container.container_id,
                        "delta": max(container.client_height * 0.8, 1),
                        "maxElements": max_elements,
                    },
                    deadline=deadline,
                ),
            )
            if not metrics.get("connected", False):
                stop_reason = "detached"
                break
            rounds += 1
            frame.page.wait_for_timeout(min(100, _remaining_milliseconds(deadline)))
            current_metrics = cast(
                _MetricsPayload,
                _carrier_request(
                    frame,
                    {
                        "operation": "inspect",
                        "containerId": container.container_id,
                        "maxElements": max_elements,
                    },
                    deadline=deadline,
                ),
            )
            if not current_metrics.get("connected", False):
                stop_reason = "detached"
                break

            current_batch = _collect_elements(
                frame,
                max_elements=max_elements,
                max_text_chars=max_text_chars,
                deadline=deadline,
            )
            text_truncated = text_truncated or current_batch.text_truncated
            remaining_elements = _append_new_elements(
                current_batch,
                known_node_ids=known_node_ids,
                discovered=discovered,
                remaining_elements=remaining_elements,
            )
            current_scoped_node_ids = set(
                current_metrics.get("descendantNodeIds", [])
            )
            new_scoped_node_count = len(current_scoped_node_ids - scoped_node_ids)
            scoped_node_ids.update(current_scoped_node_ids)

            current_height = current_metrics.get("scrollHeight", previous_height)
            if (
                new_scoped_node_count == 0
                and abs(current_height - previous_height) <= 1
            ):
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_height = current_height
            if remaining_elements == 0:
                stop_reason = "max_elements"
                truncated = True
                break
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
        _result(
            container=container,
            rounds=rounds,
            discovered=discovered,
            restored=restored,
            truncated=truncated,
            stop_reason=stop_reason,
        ),
        discovered,
        text_truncated,
    )


def _collect_elements(
    frame: Frame,
    *,
    max_elements: int,
    max_text_chars: int,
    deadline: float,
) -> _ElementBatch:
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
    elements_payload = frame_payload["elements"]
    return _ElementBatch(
        elements=tuple(
            _CollectedElement(
                node_id=payload["nodeId"],
                observation=_element_from_payload(payload, index),
            )
            for index, payload in enumerate(elements_payload["observations"])
        ),
        truncated=elements_payload["truncated"],
        text_truncated=elements_payload["textTruncated"],
    )


def _append_new_elements(
    batch: _ElementBatch,
    *,
    known_node_ids: set[str],
    discovered: list[RawElementObservation],
    remaining_elements: int,
) -> int:
    for item in batch.elements:
        if item.node_id in known_node_ids:
            continue
        if remaining_elements == 0:
            break
        known_node_ids.add(item.node_id)
        discovered.append(item.observation)
        remaining_elements -= 1
    return remaining_elements


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


def _result(
    *,
    container: ScrollContainer,
    rounds: int,
    discovered: list[RawElementObservation],
    restored: bool,
    truncated: bool,
    stop_reason: Literal[
        "stable",
        "end_reached",
        "round_limit",
        "max_elements",
        "deadline",
        "detached",
        "error",
    ],
) -> RawScrollResult:
    return RawScrollResult(
        container_id=container.container_id,
        label=container.label,
        rounds=rounds,
        discovered_elements=len(discovered),
        restored=restored,
        truncated=truncated,
        stop_reason=stop_reason,
    )


def _raise_deadline(deadline: float) -> None:
    if monotonic() >= deadline:
        raise _DeadlineReached


def _empty_result(
    *,
    container_id: str,
    label: str,
    stop_reason: Literal["max_elements", "deadline", "error"],
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
