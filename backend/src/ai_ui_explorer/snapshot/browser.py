"""Playwright-backed raw page observation."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol, TypedDict, cast

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Frame,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ai_ui_explorer.snapshot.models import (
    Bounds,
    FrameStopReason,
    LocatorParameter,
    LocatorStrategy,
    SnapshotLimits,
)

_OBSERVATION_ATTRIBUTE = "data-snapshot-observation"
_OBSERVATION_SELECTOR = "snapshot_observation"
_OBSERVATION_SELECTOR_ENGINE = """
(() => {
const observationNodeIds = new WeakMap();
let nextObservationNodeId = 0;
const interactiveSelector =
  "a[href],button,input:not([type='hidden']),select,textarea,summary,img[alt],[role],[tabindex]";
const observedAttributeNames = new Set([
  "id", "name", "type", "placeholder", "data-testid", "alt", "title",
]);
const strategyOrder = {
  testid: 0, role: 1, label: 2, text: 3, placeholder: 4,
  alt: 5, title: 6, id: 7, name: 8, aria: 9,
  css: 10, xpath: 11, position: 12,
};
const stabilityOrder = { high: 0, medium: 1, low: 2, unknown: 3 };
const sensitiveValuePattern =
  /(password|passcode|passwd|token|secret|credential|api[-_ ]?key|authorization|cookie|session)/i;
const redactionMarkerPattern = /(\\[redacted\\]|<redacted>|\\*{3,}|•{3,})/i;
const normalizeText = (value) => {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\\s+/g, " ").trim();
  return normalized || null;
};
const safeCandidateString = (value) => {
  const normalized = normalizeText(value);
  if (!normalized) return null;
  if (sensitiveValuePattern.test(normalized) || redactionMarkerPattern.test(normalized)) {
    return null;
  }
  return normalized;
};
const normalizeCandidateParameters = (parameters) => {
  const normalized = {};
  for (const key of Object.keys(parameters).sort()) {
    const value = parameters[key];
    if (typeof value === "string") {
      const safeValue = safeCandidateString(value);
      if (!safeValue) return null;
      normalized[key] = safeValue;
    } else if (typeof value === "number" || typeof value === "boolean") {
      normalized[key] = value;
    } else {
      return null;
    }
  }
  return normalized;
};
const canonicalParameters = (parameters) => JSON.stringify(parameters);
const allowedAttributeName = (name) => (
  observedAttributeNames.has(name) || name.startsWith("aria-")
);
const safeObservedAttribute = (element, name) => {
  const normalizedName = String(name).toLowerCase();
  if (!allowedAttributeName(normalizedName)) return null;
  return safeCandidateString(element.getAttribute(normalizedName));
};
const interactiveElements = (root) => {
  const elements = [];
  const visit = (scope) => {
    for (const element of scope.querySelectorAll(interactiveSelector)) {
      elements.push(element);
    }
    for (const element of scope.querySelectorAll("*")) {
      if (element.shadowRoot) visit(element.shadowRoot);
    }
  };
  visit(root);
  return elements;
};
const observationNodeIdFor = (element) => {
  let nodeId = observationNodeIds.get(element);
  if (!nodeId) {
    nextObservationNodeId += 1;
    nodeId = `observation-node-${nextObservationNodeId}`;
    observationNodeIds.set(element, nodeId);
  }
  return nodeId;
};
const collect = (root, { maxElements, maxTextChars }) => {
  let carrierTextTruncated = false;
  const clip = (value) => {
    if (typeof value !== "string") return null;
    const normalized = value.replace(/\\s+/g, " ").trim();
    if (normalized.length > maxTextChars) carrierTextTruncated = true;
    return normalized.slice(0, maxTextChars);
  };
  const body = root.querySelector("body");
  const bodyText = body?.innerText || "";
  const observations = [];
  const result = (elementsTruncated) => ({
    text: {
      text: bodyText.slice(0, maxTextChars),
      truncated: bodyText.length > maxTextChars,
    },
    elements: {
      observations,
      truncated: elementsTruncated,
      textTruncated: carrierTextTruncated,
    },
  });
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
    const elementRoot = element.getRootNode();
    return clip(
      ids.map((id) => elementRoot.getElementById?.(id)?.innerText || "").join(" ")
    );
  };
  const stateFromAria = (element, attribute) => {
    const value = element.getAttribute(attribute);
    if (value === "true") return true;
    if (value === "false") return false;
    return null;
  };
  const allElements = interactiveElements(root);
  const visibleElements = allElements.filter((element) => {
    const bounds = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return bounds.width > 0 && bounds.height > 0
      && style.display !== "none"
      && style.visibility !== "hidden";
  });
  const observed = visibleElements.map((element) => {
    const tag = element.tagName.toLowerCase();
    const href = tag === "a" && element.hasAttribute("href") ? element.href : null;
    const role = clip(element.getAttribute("role")) || implicitRole(element);
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
      if (allowedAttributeName(name)) {
        attributes[name] = clip(element.getAttribute(name)) || "";
      }
    }
    return {
      element,
      tag,
      role,
      label,
      accessibleName,
      text: clip(element.innerText),
      href,
      attributes,
      semanticDefinitions: [],
    };
  });
  for (const item of observed) {
    item.semanticDefinitions = semanticDefinitions(item);
  }
  const semanticMatchCounts = new Map();
  for (const item of observed) {
    for (const definition of item.semanticDefinitions) {
      const key =
        `${definition.strategy}\\u0000${canonicalParameters(definition.parameters)}`;
      semanticMatchCounts.set(key, (semanticMatchCounts.get(key) || 0) + 1);
    }
  }
  const countSemanticMatches = (strategy, parameters) => (
    semanticMatchCounts.get(
      `${strategy}\\u0000${canonicalParameters(parameters)}`
    ) || 0
  );
  const makeCountedCandidate = ({
    strategy, parameters, source, stability, confidence, matchCount, limitations = [],
  }) => {
    const normalizedParameters = normalizeCandidateParameters(parameters);
    if (!normalizedParameters) return null;
    const uniqueness = matchCount === null
      ? "unverified"
      : (matchCount === 1 ? "unique" : "multiple");
    return {
      strategy,
      parameters: normalizedParameters,
      source,
      uniqueness,
      matchCount,
      stability,
      confidence,
      rank: 0,
      recommended: matchCount === 1 && strategy !== "position",
      limitations,
    };
  };
  function semanticDefinitions(item) {
    const definitions = [];
    const add = (strategy, parameters, stability, confidence) => {
      const normalizedParameters = normalizeCandidateParameters(parameters);
      if (!normalizedParameters) return;
      definitions.push({
        strategy,
        parameters: normalizedParameters,
        source: "observed",
        stability,
        confidence,
      });
    };
    const testId = safeObservedAttribute(item.element, "data-testid");
    const placeholder = safeObservedAttribute(item.element, "placeholder");
    const alt = safeObservedAttribute(item.element, "alt");
    const title = safeObservedAttribute(item.element, "title");
    const id = safeObservedAttribute(item.element, "id");
    const name = safeObservedAttribute(item.element, "name");
    const ariaLabel = safeObservedAttribute(item.element, "aria-label");
    if (testId) add("testid", { value: testId }, "high", 0.99);
    if (item.role && item.accessibleName) {
      add(
        "role",
        { role: item.role, name: item.accessibleName, exact: true },
        "high",
        0.95,
      );
    }
    if (item.label) add("label", { value: item.label, exact: true }, "high", 0.95);
    if (item.text) add("text", { value: item.text, exact: true }, "medium", 0.75);
    if (placeholder) {
      add("placeholder", { value: placeholder, exact: true }, "medium", 0.85);
    }
    if (alt) add("alt", { value: alt, exact: true }, "medium", 0.85);
    if (title) add("title", { value: title, exact: true }, "medium", 0.8);
    if (id) add("id", { value: id }, "high", 0.9);
    if (name) add("name", { value: name }, "medium", 0.8);
    if (ariaLabel) {
      add(
        "aria",
        { attribute: "aria-label", value: ariaLabel },
        "medium",
        0.8,
      );
    }
    return definitions;
  }
  const structuralSegments = (element) => {
    const segments = [];
    let current = element;
    while (current instanceof Element && segments.length < 4) {
      const tag = current.tagName.toLowerCase();
      segments.push({ css: tag, xpath: tag });
      current = current.parentElement;
    }
    return segments.reverse();
  };
  const cssMatchCounts = new Map();
  const xpathMatchCounts = new Map();
  const cssCandidate = (element) => {
    const selector = structuralSegments(element).map((item) => item.css).join(" > ");
    if (!selector || selector.length > 256) return null;
    if (element.getRootNode() !== document) {
      return makeCountedCandidate({
        strategy: "css",
        parameters: { selector },
        source: "generated",
        stability: "low",
        confidence: 0.4,
        matchCount: null,
        limitations: ["shadow_root_scope_unmodeled"],
      });
    }
    try {
      let matchCount = cssMatchCounts.get(selector);
      if (matchCount === undefined) {
        matchCount = document.querySelectorAll(selector).length;
        cssMatchCounts.set(selector, matchCount);
      }
      return makeCountedCandidate({
        strategy: "css",
        parameters: { selector },
        source: "generated",
        stability: "low",
        confidence: 0.6,
        matchCount,
      });
    } catch {
      return null;
    }
  };
  const xpathCandidate = (element) => {
    const expression =
      `//${structuralSegments(element).map((item) => item.xpath).join("/")}`;
    if (!expression || expression.length > 256) return null;
    if (element.getRootNode() !== document) {
      return makeCountedCandidate({
        strategy: "xpath",
        parameters: { expression },
        source: "generated",
        stability: "low",
        confidence: 0.3,
        matchCount: null,
        limitations: [
          "shadow_root_scope_unmodeled",
          "document_xpath_cannot_pierce_shadow_root",
        ],
      });
    }
    try {
      let matchCount = xpathMatchCounts.get(expression);
      if (matchCount === undefined) {
        const matches = document.evaluate(
          expression,
          document,
          null,
          XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
          null,
        );
        matchCount = matches.snapshotLength;
        xpathMatchCounts.set(expression, matchCount);
      }
      return makeCountedCandidate({
        strategy: "xpath",
        parameters: { expression },
        source: "generated",
        stability: "low",
        confidence: 0.5,
        matchCount,
      });
    } catch {
      return null;
    }
  };
  const locatorCandidates = (item, bounds) => {
    const candidates = [];
    for (const definition of item.semanticDefinitions) {
      const candidate = makeCountedCandidate({
        ...definition,
        matchCount: countSemanticMatches(
          definition.strategy,
          definition.parameters,
        ),
      });
      if (candidate) candidates.push(candidate);
    }
    const css = cssCandidate(item.element);
    if (css) candidates.push(css);
    const xpath = xpathCandidate(item.element);
    if (xpath) candidates.push(xpath);
    candidates.push({
      strategy: "position",
      parameters: {
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
      },
      source: "observed",
      uniqueness: "unverified",
      matchCount: null,
      stability: "low",
      confidence: 1.0,
      rank: 0,
      recommended: false,
      limitations: ["viewport_and_scroll_dependent"],
    });
    candidates.sort((left, right) => {
      const leftRecommended = left.recommended && left.uniqueness === "unique" ? 0 : 1;
      const rightRecommended = right.recommended && right.uniqueness === "unique" ? 0 : 1;
      return leftRecommended - rightRecommended
        || stabilityOrder[left.stability] - stabilityOrder[right.stability]
        || strategyOrder[left.strategy] - strategyOrder[right.strategy]
        || canonicalParameters(left.parameters).localeCompare(
          canonicalParameters(right.parameters)
        );
    });
    return candidates.slice(0, 12).map(
      (candidate, index) => ({ ...candidate, rank: index + 1 })
    );
  };
  for (const item of observed) {
    const element = item.element;
    if (observations.length >= maxElements) {
      return result(true);
    }

    const { tag, role, label, accessibleName, text, href, attributes } = item;
    const bounds = element.getBoundingClientRect();

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

    observations.push({
      nodeId: observationNodeIdFor(element),
      tag,
      role,
      accessibleName,
      text,
      href,
      attributes,
      visible: true,
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
      locatorCandidates: locatorCandidates(item, bounds),
    });
  }
  return result(false);
};
const query = (root, selector) => {
  const payload = collect(root, JSON.parse(selector));
  const documentNode = root.nodeType === Node.DOCUMENT_NODE ? root : root.ownerDocument;
  const carrier = documentNode.createElement("meta");
  carrier.setAttribute("data-snapshot-observation", JSON.stringify(payload));
  return carrier;
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
class RawLocatorCandidate:
    strategy: LocatorStrategy
    parameters: dict[str, LocatorParameter]
    source: Literal["observed", "generated"]
    uniqueness: Literal["unique", "multiple", "unverified"]
    match_count: int | None
    stability: Literal["high", "medium", "low", "unknown"]
    confidence: float
    rank: int
    recommended: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawElementObservation:
    traversal_index: int
    tag: str
    role: str | None
    accessible_name: str | None
    text: str | None
    href: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: Bounds | None
    locator_candidates: tuple[RawLocatorCandidate, ...]


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
        "max_elements",
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
    stop_reason: FrameStopReason | None


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
        _configure_local_browser_path()
        deadline = monotonic() + (limits.total_timeout_ms / 1_000)
        with _managed_page(headless=self._headless, deadline=deadline) as page:
            return _collect_page_observation(
                page=page,
                url=url,
                limits=limits,
                deadline=deadline,
            )


class PlaywrightBrowserSession:
    def __init__(
        self,
        *,
        playwright: Playwright,
        browser: Browser,
        context: BrowserContext,
        page: Page,
        headless: bool,
    ) -> None:
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._page = page
        self._headless = headless
        self._closed = False

    @classmethod
    def open(cls, *, headless: bool) -> PlaywrightBrowserSession:
        _configure_local_browser_path()
        playwright = sync_playwright().start()
        try:
            _register_custom_selectors(playwright)
            browser = _launch_browser(playwright, headless=headless)
        except BaseException:
            with suppress(PlaywrightError):
                playwright.stop()
            raise
        try:
            context = browser.new_context()
        except BaseException:
            with suppress(PlaywrightError):
                browser.close()
            with suppress(PlaywrightError):
                playwright.stop()
            raise
        try:
            page = context.new_page()
        except BaseException:
            with suppress(PlaywrightError):
                context.close()
            with suppress(PlaywrightError):
                browser.close()
            with suppress(PlaywrightError):
                playwright.stop()
            raise
        return cls(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            headless=headless,
        )

    @property
    def is_headless(self) -> bool:
        return self._headless

    @property
    def current_url(self) -> str:
        return self._page.url

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

    def has_css(self, selector: str) -> bool:
        return self._page.locator(selector).count() > 0

    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        deadline = monotonic() + (limits.total_timeout_ms / 1_000)
        return _collect_page_observation(
            page=self._page,
            url=url,
            limits=limits,
            deadline=deadline,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(PlaywrightError):
            self._page.close()
        with suppress(PlaywrightError):
            self._context.close()
        with suppress(PlaywrightError):
            self._browser.close()
        with suppress(PlaywrightError):
            self._playwright.stop()


def _collect_page_observation(
    *,
    page: Page,
    url: str,
    limits: SnapshotLimits,
    deadline: float,
) -> RawPageObservation:
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=_remaining_milliseconds(deadline),
    )
    _raise_if_deadline_reached(deadline)
    _wait_for_dynamic_frames(page, deadline)
    _raise_if_deadline_reached(deadline)

    ordered_frames = _ordered_frames(page.main_frame)
    page_errors: list[RawErrorObservation] = []
    frame_limit_reached = len(ordered_frames) > limits.max_frames
    if frame_limit_reached:
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
        frame_observation = (
            _element_budget_exhausted_frame(
                frame=frame,
                frame_id=frame_ids[id(frame)],
                frame_ids=frame_ids,
                traversal_index=traversal_index,
            )
            if remaining_elements == 0
            else _observe_frame(
                frame=frame,
                frame_id=frame_ids[id(frame)],
                frame_ids=frame_ids,
                traversal_index=traversal_index,
                remaining_elements=remaining_elements,
                limits=limits,
                deadline=deadline,
            )
        )
        frames.append(frame_observation)
        observed_elements += len(frame_observation.elements)
        deadline_reached = deadline_reached or frame_observation.stop_reason == "deadline"

    if frame_limit_reached and frames:
        root_frame = frames[0]
        if root_frame.status == "completed":
            root_frame.status = "partial"
        root_frame.truncated = True
        if root_frame.stop_reason is None:
            root_frame.stop_reason = "max_frames"

    viewport = page.viewport_size or {"width": 1280, "height": 720}
    if deadline_reached:
        language = None
        title = ""
    else:
        language = page.locator("html").get_attribute(
            "lang",
            timeout=_remaining_milliseconds(deadline),
        )
        _raise_if_deadline_reached(deadline)
        page.set_default_timeout(_remaining_milliseconds(deadline))
        title = page.title()
        _raise_if_deadline_reached(deadline)
    return RawPageObservation(
        final_url=page.url,
        title=title,
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


class _RawLocatorCandidatePayload(TypedDict):
    strategy: str
    parameters: dict[str, LocatorParameter]
    source: str
    uniqueness: str
    matchCount: int | None
    stability: str
    confidence: float
    rank: int
    recommended: bool
    limitations: list[str]


class _RawElementPayload(TypedDict):
    nodeId: str
    tag: str
    role: str | None
    accessibleName: str | None
    text: str | None
    href: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: _RawBoundsPayload | None
    locatorCandidates: list[_RawLocatorCandidatePayload]


class _RawTextPayload(TypedDict):
    text: str
    truncated: bool


class _RawElementsPayload(TypedDict):
    observations: list[_RawElementPayload]
    truncated: bool
    textTruncated: bool


class _RawFramePayload(TypedDict):
    text: _RawTextPayload
    elements: _RawElementsPayload


@contextmanager
def _managed_page(*, headless: bool, deadline: float) -> Iterator[Page]:
    with sync_playwright() as playwright:
        _register_custom_selectors(playwright)
        browser = _launch_browser(
            playwright,
            headless=headless,
            timeout=_remaining_milliseconds(deadline),
        )

        try:
            _raise_if_deadline_reached(deadline)
            context = browser.new_context()
            try:
                _raise_if_deadline_reached(deadline)
                page = context.new_page()
                try:
                    _raise_if_deadline_reached(deadline)
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


def _register_custom_selectors(playwright: Playwright) -> None:
    playwright.selectors.register(
        _OBSERVATION_SELECTOR,
        script=_OBSERVATION_SELECTOR_ENGINE,
        content_script=True,
    )
    from ai_ui_explorer.snapshot.scrolling import (
        _SCROLL_SELECTOR,
        _SCROLL_SELECTOR_ENGINE,
    )

    playwright.selectors.register(
        _SCROLL_SELECTOR,
        script=_SCROLL_SELECTOR_ENGINE,
        content_script=True,
    )


def _launch_browser(
    playwright: Playwright,
    *,
    headless: bool,
    timeout: int | None = None,
) -> Browser:
    try:
        if timeout is None:
            return playwright.chromium.launch(headless=headless)
        return playwright.chromium.launch(headless=headless, timeout=timeout)
    except PlaywrightError as exc:
        if "executable doesn't exist" in str(exc).lower():
            raise BrowserUnavailableError(_browser_install_guidance()) from None
        raise


def _remaining_milliseconds(deadline: float) -> int:
    remaining = int((deadline - monotonic()) * 1_000)
    if remaining <= 0:
        raise _DeadlineReached
    return remaining


def _raise_if_deadline_reached(deadline: float) -> None:
    if monotonic() >= deadline:
        raise _DeadlineReached


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
    text_summary = ""
    elements: list[RawElementObservation] = []
    try:
        _raise_if_deadline_reached(deadline)
        if frame.url:
            frame.wait_for_load_state(
                "domcontentloaded",
                timeout=_remaining_milliseconds(deadline),
            )
        else:
            frame.wait_for_url(
                lambda current_url: bool(current_url),
                wait_until="domcontentloaded",
                timeout=_remaining_milliseconds(deadline),
            )
        _raise_if_deadline_reached(deadline)
        selector_argument = json.dumps(
            {
                "maxElements": remaining_elements,
                "maxTextChars": limits.max_text_chars,
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
        text_payload = frame_payload["text"]
        text_summary = text_payload["text"]
        elements_payload = frame_payload["elements"]
        _raise_if_deadline_reached(deadline)
        elements = [
            _element_from_payload(payload, index)
            for index, payload in enumerate(elements_payload["observations"])
        ]
        from ai_ui_explorer.snapshot.scrolling import collect_with_scrolling

        if remaining_elements > 0:
            scrolling_limits = limits.model_copy(
                update={"max_elements": remaining_elements}
            )
            scrolling_observation = collect_with_scrolling(
                frame,
                scrolling_limits,
                deadline,
                initial_payload=frame_payload,
            )
            elements = scrolling_observation.elements
            scroll_results = scrolling_observation.scroll_results
            scroll_text_truncated = scrolling_observation.text_truncated
            container_limit_reached = (
                scrolling_observation.container_limit_reached
            )
        else:
            scroll_results = []
            scroll_text_truncated = False
            container_limit_reached = False
    except (_DeadlineReached, PlaywrightTimeoutError) as exc:
        error = _raw_error(
            scope=f"frame:{frame_id}",
            error_code="deadline_reached",
            message=(
                "Frame observation stopped at the global deadline."
                if isinstance(exc, _DeadlineReached)
                else str(exc)
            ),
        )
        return RawFrameObservation(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            traversal_index=traversal_index,
            depth=depth,
            name=name,
            url=url,
            status="partial" if text_summary or elements else "failed",
            text_summary=text_summary,
            elements=elements,
            scroll_results=[],
            errors=[error],
            truncated=True,
            stop_reason="deadline",
        )
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

    element_truncated = elements_payload["truncated"]
    text_truncated = (
        text_payload["truncated"]
        or elements_payload["textTruncated"]
        or scroll_text_truncated
    )
    scroll_deadline = next(
        (
            result
            for result in scroll_results
            if result.stop_reason == "deadline"
        ),
        None,
    )
    scroll_error = next(
        (
            result
            for result in scroll_results
            if result.stop_reason == "error"
        ),
        None,
    )
    scroll_detached = next(
        (
            result
            for result in scroll_results
            if result.stop_reason == "detached"
        ),
        None,
    )
    scroll_errors = (
        [
            _raw_error(
                scope=f"frame:{frame_id}",
                error_code="deadline_reached",
                message="Frame scrolling stopped at the global deadline.",
            )
        ]
        if scroll_deadline is not None
        else (
            [
                _raw_error(
                    scope=f"frame:{frame_id}",
                    error_code="scroll_container_detached",
                    message="A scroll container detached during observation.",
                )
            ]
            if scroll_detached is not None
            else (
                [
                    _raw_error(
                        scope=f"frame:{frame_id}",
                        error_code="scroll_observation_failed",
                        message="A scroll container could not be observed.",
                    )
                ]
                if scroll_error is not None
                else []
            )
        )
    )
    scroll_truncated = container_limit_reached or any(
        result.truncated or result.stop_reason == "detached"
        for result in scroll_results
    )
    truncated = element_truncated or text_truncated or scroll_truncated
    prioritized_scroll_reason = next(
        (
            reason
            for reason in ("deadline", "max_elements")
            if any(result.stop_reason == reason for result in scroll_results)
        ),
        None,
    )
    failure_scroll_reason = next(
        (
            reason
            for reason in ("detached", "error")
            if any(result.stop_reason == reason for result in scroll_results)
        ),
        None,
    )
    stop_reason = cast(
        FrameStopReason | None,
        (
            prioritized_scroll_reason
            or ("max_scroll_containers" if container_limit_reached else None)
            or failure_scroll_reason
            or ("max_elements" if element_truncated else None)
            or ("max_text_chars" if text_truncated else None)
            or next(
                (
                    result.stop_reason
                    for result in scroll_results
                    if result.truncated
                ),
                None,
            )
        )
    )
    return RawFrameObservation(
        frame_id=frame_id,
        parent_frame_id=parent_frame_id,
        traversal_index=traversal_index,
        depth=depth,
        name=name,
        url=url,
        status="partial" if truncated or scroll_errors else "completed",
        text_summary=text_summary,
        elements=elements,
        scroll_results=scroll_results,
        errors=scroll_errors,
        truncated=truncated,
        stop_reason=stop_reason,
    )


def _element_budget_exhausted_frame(
    *,
    frame: Frame,
    frame_id: str,
    frame_ids: dict[int, str],
    traversal_index: int,
) -> RawFrameObservation:
    parent = frame.parent_frame
    return RawFrameObservation(
        frame_id=frame_id,
        parent_frame_id=frame_ids.get(id(parent)) if parent is not None else None,
        traversal_index=traversal_index,
        depth=_frame_depth(frame),
        name="main" if parent is None else (frame.name or frame_id),
        url=frame.url,
        status="partial",
        text_summary="",
        elements=[],
        scroll_results=[],
        errors=[],
        truncated=True,
        stop_reason="max_elements",
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
    locator_candidates = tuple(
        _locator_candidate_from_payload(candidate)
        for candidate in payload["locatorCandidates"]
    )
    return RawElementObservation(
        traversal_index=traversal_index,
        tag=payload["tag"],
        role=payload["role"],
        accessible_name=payload["accessibleName"],
        text=payload["text"],
        href=payload.get("href"),
        attributes=payload["attributes"],
        visible=payload["visible"],
        enabled=payload["enabled"],
        checked=payload["checked"],
        selected=payload["selected"],
        expanded=payload["expanded"],
        bounds=bounds,
        locator_candidates=locator_candidates,
    )


def _locator_candidate_from_payload(
    payload: _RawLocatorCandidatePayload,
) -> RawLocatorCandidate:
    strategy = payload["strategy"]
    if strategy not in {
        "role",
        "label",
        "text",
        "placeholder",
        "alt",
        "title",
        "testid",
        "id",
        "name",
        "aria",
        "css",
        "xpath",
        "position",
    }:
        raise ValueError(f"Unknown locator strategy: {strategy}")
    source = payload["source"]
    if source not in {"observed", "generated"}:
        raise ValueError(f"Unknown locator source: {source}")
    uniqueness = payload["uniqueness"]
    if uniqueness not in {"unique", "multiple", "unverified"}:
        raise ValueError(f"Unknown locator uniqueness: {uniqueness}")
    stability = payload["stability"]
    if stability not in {"high", "medium", "low", "unknown"}:
        raise ValueError(f"Unknown locator stability: {stability}")
    return RawLocatorCandidate(
        strategy=cast(LocatorStrategy, strategy),
        parameters=payload["parameters"],
        source=cast(Literal["observed", "generated"], source),
        uniqueness=cast(
            Literal["unique", "multiple", "unverified"],
            uniqueness,
        ),
        match_count=payload["matchCount"],
        stability=cast(
            Literal["high", "medium", "low", "unknown"],
            stability,
        ),
        confidence=payload["confidence"],
        rank=payload["rank"],
        recommended=payload["recommended"],
        limitations=tuple(payload["limitations"]),
    )


def _raw_error(*, scope: str, error_code: str, message: str) -> RawErrorObservation:
    return RawErrorObservation(
        scope=scope,
        error_code=error_code,
        message=message,
        recoverable=True,
        occurred_at=datetime.now(UTC),
    )


class _DeadlineReached(RuntimeError):
    """Internal signal used to preserve a raw partial observation at the deadline."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _configure_local_browser_path() -> Path:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return Path(configured)
    local_browser_path = _project_root() / ".playwright-browsers"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_browser_path)
    return local_browser_path


def _browser_install_guidance() -> str:
    browser_path = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
    local_python = _project_root() / ".venv" / "Scripts" / "python.exe"
    quoted_browser_path = str(browser_path).replace("'", "''")
    quoted_python = str(local_python).replace("'", "''")
    return (
        "Project-local Chromium is unavailable. "
        "Set the current PowerShell process and install it:\n"
        f"$env:PLAYWRIGHT_BROWSERS_PATH = '{quoted_browser_path}'\n"
        f"& '{quoted_python}' -m playwright install chromium"
    )
