"""Real Chromium tests for initial page and frame observation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin

import pytest

from ai_ui_explorer.snapshot import browser as browser_module
from ai_ui_explorer.snapshot.browser import BrowserUnavailableError, PlaywrightBrowserSource
from ai_ui_explorer.snapshot.collector import SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotLimits

from . import conftest as fixture_support


def test_browser_observes_main_same_origin_cross_origin_and_dynamic_frames(
    primary_url: str,
) -> None:
    """Dropping any supported frame kind or semantic element breaks collection."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        primary_url,
        SnapshotLimits(),
    )

    frames_by_name = {frame.name: frame for frame in observation.frames}
    assert {"main", "same-origin", "nested", "cross-origin", "dynamic"} <= frames_by_name.keys()
    assert any(
        element.accessible_name == "保存草稿"
        for frame in observation.frames
        for element in frame.elements
    )

    positions = {frame.frame_id: position for position, frame in enumerate(observation.frames)}
    assert observation.frames[0].parent_frame_id is None
    assert all(
        frame.parent_frame_id is None
        or positions[frame.parent_frame_id] < positions[frame.frame_id]
        for frame in observation.frames
    )
    assert frames_by_name["nested"].parent_frame_id == frames_by_name["same-origin"].frame_id


def test_browser_does_not_observe_input_values_or_disallowed_page_content(
    primary_url: str,
) -> None:
    """Password values, hidden values, and arbitrary attributes must never leave Chromium."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        primary_url,
        SnapshotLimits(),
    )

    raw_output = repr(observation)
    assert "fixture-password-do-not-return" not in raw_output
    assert "fixture-hidden-do-not-return" not in raw_output
    assert "outerHTML" not in raw_output
    assert all(
        "value" not in element.attributes
        and "data-private" not in element.attributes
        and element.visible
        for frame in observation.frames
        for element in frame.elements
    )


def test_page_prototype_override_cannot_exfiltrate_input_value(primary_url: str) -> None:
    """Page-world DOM prototype poisoning cannot alter utility-world observations."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        primary_url,
        SnapshotLimits(),
    )

    raw_output = repr(observation)
    assert "fixture-password-do-not-return" not in raw_output
    save_button = next(
        element
        for frame in observation.frames
        for element in frame.elements
        if element.accessible_name == "保存草稿"
    )
    assert save_button.attributes["id"] == "save-draft"
    assert save_button.attributes["data-testid"] == "save-draft"


def test_browser_collects_ranked_bounded_locator_candidates(
    locator_page_url: str,
) -> None:
    """Dropping ranking, the hard cap, or positional fallback breaks raw collection."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    submit = next(
        element
        for frame in raw_page.frames
        for element in frame.elements
        if element.accessible_name == "Submit order"
    )

    assert submit.locator_candidates
    assert submit.locator_candidates[0].rank == 1
    assert [item.rank for item in submit.locator_candidates] == list(
        range(1, len(submit.locator_candidates) + 1)
    )
    assert any(item.strategy == "role" for item in submit.locator_candidates)
    assert any(item.strategy == "position" for item in submit.locator_candidates)
    assert len(submit.locator_candidates) <= 12


def test_browser_enforces_candidate_cap_and_deterministic_full_order(
    locator_page_url: str,
) -> None:
    """Removing the cap or reordering any stability/strategy tier must fail."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    target = next(
        element
        for frame in raw_page.frames
        for element in frame.elements
        if element.accessible_name == "Candidate cap accessible name"
    )

    assert len(target.locator_candidates) == 12
    assert [item.strategy for item in target.locator_candidates] == [
        "testid",
        "role",
        "label",
        "id",
        "text",
        "placeholder",
        "alt",
        "title",
        "name",
        "aria",
        "css",
        "xpath",
    ]
    assert [item.rank for item in target.locator_candidates] == list(range(1, 13))


def test_browser_collects_semantic_locator_strategies(
    locator_page_url: str,
) -> None:
    """Each allowlisted semantic source must survive as an explainable candidate."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    elements = {
        element.accessible_name: element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
    }
    expected = {
        "Labelled account": "label",
        "Placeholder only": "placeholder",
        "Illustrated account": "alt",
        "Open settings": "title",
        "Test id target": "testid",
        "Unique id target": "id",
        "Unique name target": "name",
    }

    for accessible_name, strategy in expected.items():
        assert any(
            item.strategy == strategy
            for item in elements[accessible_name].locator_candidates
        ), (accessible_name, strategy, elements[accessible_name].locator_candidates)


def test_text_semantic_candidates_use_exact_playwright_matching(
    locator_page_url: str,
) -> None:
    """Semantic counts and replay parameters must share exact text matching."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    elements = {
        element.accessible_name: element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
    }
    expected = {
        ("Submit order", "role"),
        ("Labelled account", "label"),
        ("Submit order", "text"),
        ("Placeholder only", "placeholder"),
        ("Illustrated account", "alt"),
        ("Open settings", "title"),
    }

    for accessible_name, strategy in expected:
        candidate = next(
            item
            for item in elements[accessible_name].locator_candidates
            if item.strategy == strategy
        )
        assert candidate.parameters["exact"] is True
    duplicate_role = next(
        item
        for item in elements["Duplicate action"].locator_candidates
        if item.strategy == "role"
    )
    assert duplicate_role.parameters == {
        "exact": True,
        "name": "Duplicate action",
        "role": "button",
    }
    assert duplicate_role.match_count == 2
    assert duplicate_role.uniqueness == "multiple"


def test_browser_marks_duplicate_semantic_candidates_not_recommended(
    locator_page_url: str,
) -> None:
    """A duplicate role/name cannot be presented as a unique recommendation."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    duplicates = [
        element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
        if element.accessible_name == "Duplicate action"
    ]

    assert len(duplicates) == 2
    for element in duplicates:
        role = next(
            item for item in element.locator_candidates if item.strategy == "role"
        )
        assert role.uniqueness == "multiple"
        assert role.match_count == 2
        assert role.recommended is False


def test_browser_semantic_count_ignores_hidden_same_name_elements(
    locator_page_url: str,
) -> None:
    """A hidden namesake must not inflate the visible-interactive match count."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    duplicate = next(
        element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
        if element.accessible_name == "Duplicate action"
    )
    role = next(
        item for item in duplicate.locator_candidates if item.strategy == "role"
    )

    assert role.match_count == 2


def test_browser_ranks_testid_above_structural_candidates(
    locator_page_url: str,
) -> None:
    """A stable observed test id must outrank generated DOM structure."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    target = next(
        element
        for frame in raw_page.frames
        for element in frame.elements
        if element.accessible_name == "Test id target"
    )
    ranks = {item.strategy: item.rank for item in target.locator_candidates}

    assert ranks["testid"] < ranks["css"]
    assert ranks["testid"] < ranks["xpath"]


def test_browser_bounds_structural_candidates_and_excludes_sensitive_values(
    locator_page_url: str,
) -> None:
    """Selectors stay bounded and never inherit page secrets or dynamic classes."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    target = next(
        element
        for frame in raw_page.frames
        for element in frame.elements
        if element.accessible_name == "Bounded structural target"
    )
    css = next(item for item in target.locator_candidates if item.strategy == "css")
    xpath = next(
        item for item in target.locator_candidates if item.strategy == "xpath"
    )
    css_selector = cast(str, css.parameters["selector"])
    xpath_expression = cast(str, xpath.parameters["expression"])
    raw_candidates = repr(
        [
            candidate.parameters
            for frame in raw_page.frames
            for element in frame.elements
            for candidate in element.locator_candidates
        ]
    )

    assert len(css_selector) <= 256
    assert len(css_selector.split(" > ")) <= 4
    assert len(xpath_expression) <= 256
    assert len(xpath_expression.removeprefix("//").split("/")) <= 4
    for forbidden in (
        "fixture-password-attribute-do-not-return",
        "fixture-token-attribute-do-not-return",
        "fixture-token-allowlisted-do-not-return",
        "fixture-password-allowlisted-do-not-return",
        "[REDACTED]",
        "css-1a2b3c-dynamic-looking",
        "fixture-input-value-do-not-return",
    ):
        assert forbidden not in raw_candidates
    position = next(
        item for item in target.locator_candidates if item.strategy == "position"
    )
    assert position.stability == "low"
    assert position.source == "observed"
    assert position.uniqueness == "unverified"
    assert position.match_count is None
    assert position.confidence == 1.0
    assert position.recommended is False
    assert position.limitations == ("viewport_and_scroll_dependent",)
    assert target.bounds is not None
    assert position.parameters == {
        "x": target.bounds.x,
        "y": target.bounds.y,
        "width": target.bounds.width,
        "height": target.bounds.height,
        "viewportWidth": raw_page.viewport_width,
        "viewportHeight": raw_page.viewport_height,
    }


def test_browser_counts_duplicate_bounded_css_and_xpath_matches(
    locator_page_url: str,
) -> None:
    """Structural counts must come from the Frame DOM, not assumed uniqueness."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    target = next(
        element
        for frame in raw_page.frames
        for element in frame.elements
        if element.accessible_name == "Structural twin A"
    )

    for strategy in ("css", "xpath"):
        candidate = next(
            item for item in target.locator_candidates if item.strategy == strategy
        )
        assert candidate.match_count == 2
        assert candidate.uniqueness == "multiple"
        assert candidate.recommended is False


def test_browser_semantic_counting_stays_within_large_frame_deadline(
    locator_page_url: str,
) -> None:
    """Semantic duplicate counting must remain bounded on a large visible Frame."""
    bulk_url = f"{locator_page_url}&bulk=1500"
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        bulk_url,
        SnapshotLimits(total_timeout_ms=10_000, max_elements=2_000),
    )
    bulk = [
        element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
        if element.accessible_name == "Bulk duplicate"
    ]

    assert raw_page.deadline_reached is False
    assert len(bulk) == 1_500
    role = next(
        item for item in bulk[0].locator_candidates if item.strategy == "role"
    )
    assert role.match_count == 1_500
    assert role.uniqueness == "multiple"


def test_document_structural_counting_stays_within_large_frame_deadline(
    locator_page_url: str,
) -> None:
    """Same-document siblings must not trigger per-element DOM-wide selector scans."""
    bulk_url = f"{locator_page_url}&documentBulk=1500"
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        bulk_url,
        SnapshotLimits(total_timeout_ms=10_000, max_elements=2_000),
    )
    bulk = [
        element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
        if element.accessible_name == "Document bulk duplicate"
    ]

    assert raw_page.deadline_reached is False
    assert len(bulk) == 1_500
    for strategy in ("css", "xpath"):
        candidate = next(
            item for item in bulk[0].locator_candidates if item.strategy == strategy
        )
        assert candidate.match_count is not None
        assert candidate.match_count >= 1_500
        assert candidate.uniqueness == "multiple"
        assert candidate.recommended is False


def test_browser_collects_shadow_dom_and_scopes_cross_origin_candidates(
    locator_page_url: str,
) -> None:
    """Open Shadow DOM remains observable and semantic counts stay Frame-local."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    shadow = next(
        element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
        if element.accessible_name == "Shadow action"
    )
    cross_frame = next(frame for frame in raw_page.frames if frame.name == "cross-origin")
    cross = next(
        element
        for element in cross_frame.elements
        if element.accessible_name == "跨源虚构操作"
    )
    cross_role = next(
        item for item in cross.locator_candidates if item.strategy == "role"
    )

    assert shadow.locator_candidates
    assert any(item.strategy == "testid" for item in shadow.locator_candidates)
    assert cross.locator_candidates
    assert cross_role.uniqueness == "unique"
    assert cross_role.match_count == 1


def test_shadow_dom_structural_candidates_expose_unmodeled_scope(
    locator_page_url: str,
) -> None:
    """A ShadowRoot-local selector must never be reported as Frame-unique."""
    raw_page = PlaywrightBrowserSource(headless=True).collect(
        locator_page_url,
        SnapshotLimits(),
    )
    shadow_elements = [
        element
        for frame in raw_page.frames
        if frame.name == "main"
        for element in frame.elements
        if element.accessible_name in {"Shadow action", "Shadow action second"}
    ]

    assert len(shadow_elements) == 2
    css_selectors = {
        candidate.parameters["selector"]
        for element in shadow_elements
        for candidate in element.locator_candidates
        if candidate.strategy == "css"
    }
    assert len(css_selectors) == 1
    for element in shadow_elements:
        css = next(
            candidate
            for candidate in element.locator_candidates
            if candidate.strategy == "css"
        )
        xpath = next(
            candidate
            for candidate in element.locator_candidates
            if candidate.strategy == "xpath"
        )
        assert css.match_count is None
        assert css.uniqueness == "unverified"
        assert css.recommended is False
        assert css.limitations == ("shadow_root_scope_unmodeled",)
        assert xpath.match_count is None
        assert xpath.uniqueness == "unverified"
        assert xpath.recommended is False
        assert xpath.limitations == (
            "shadow_root_scope_unmodeled",
            "document_xpath_cannot_pierce_shadow_root",
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("strategy", "unsupported"),
        ("source", "inferred"),
        ("uniqueness", "sometimes"),
        ("stability", "volatile"),
    ],
)
def test_element_payload_rejects_unknown_locator_vocabulary(
    field: str,
    invalid_value: str,
) -> None:
    """Malformed selector-carrier vocabulary must fail closed at the Python boundary."""
    candidate: dict[str, Any] = {
        "strategy": "role",
        "parameters": {"role": "button", "name": "Submit order"},
        "source": "observed",
        "uniqueness": "unique",
        "matchCount": 1,
        "stability": "high",
        "confidence": 0.95,
        "rank": 1,
        "recommended": True,
        "limitations": [],
    }
    candidate[field] = invalid_value
    payload: dict[str, Any] = {
        "nodeId": "observation-node-1",
        "tag": "button",
        "role": "button",
        "accessibleName": "Submit order",
        "text": "Submit order",
        "attributes": {},
        "visible": True,
        "enabled": True,
        "checked": None,
        "selected": None,
        "expanded": None,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 32},
        "locatorHints": [],
        "locatorCandidates": [candidate],
    }

    with pytest.raises(ValueError, match=invalid_value):
        browser_module._element_from_payload(cast(Any, payload), 0)


def test_element_limit_marks_frame_partial_and_truncated(primary_url: str) -> None:
    """An extra visible element beyond the limit must not be silently discarded."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        primary_url,
        SnapshotLimits(max_elements=1),
    )

    main_frame = observation.frames[0]
    assert len([element for frame in observation.frames for element in frame.elements]) == 1
    assert main_frame.status == "partial"
    assert main_frame.truncated is True
    assert main_frame.stop_reason == "max_elements"


def test_text_limit_marks_frame_partial_and_truncated(primary_url: str) -> None:
    """Body text clipping must be observable instead of looking completed."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        f"{primary_url}&scrollFixture=identity",
        SnapshotLimits(max_text_chars=10),
    )

    main_frame = observation.frames[0]
    assert len(main_frame.text_summary) == 10
    assert main_frame.status == "partial"
    assert main_frame.truncated is True
    assert main_frame.stop_reason == "max_text_chars"


def test_frame_limit_marks_root_and_document_partial_and_truncated(
    primary_url: str,
) -> None:
    """Omitted Frames must be represented as truncation, not only a page error."""
    snapshot = SnapshotCollector(source=PlaywrightBrowserSource(headless=True)).collect(
        f"{primary_url}&scrollFixture=identity",
        SnapshotLimits(
            max_frames=1,
            max_scroll_rounds_per_container=10,
        ),
    )

    assert len(snapshot.frames) == 1
    assert snapshot.status == "partial"
    assert snapshot.truncated is True
    assert snapshot.frames[0].status == "partial"
    assert snapshot.frames[0].truncated is True
    assert snapshot.frames[0].stop_reason == "max_frames"
    assert "max_frames_reached" in {error.error_code for error in snapshot.errors}


def test_element_carrier_text_clipping_marks_frame_and_document_truncated(
    primary_url: str,
) -> None:
    """A clipped aria-label/attribute must not be confused with element exhaustion."""
    snapshot = SnapshotCollector(source=PlaywrightBrowserSource(headless=True)).collect(
        urljoin(primary_url, "/carrier-clipping.html"),
        SnapshotLimits(max_text_chars=10),
    )

    frame = snapshot.frames[0]
    assert frame.text_summary == ""
    assert frame.elements[0].accessible_name == "用于验证元素字段裁剪"
    assert frame.status == "partial"
    assert frame.truncated is True
    assert frame.stop_reason == "max_text_chars"
    assert snapshot.status == "partial"
    assert snapshot.truncated is True


def test_frame_crossing_global_deadline_cannot_be_completed(primary_url: str) -> None:
    """A deliberately delayed Frame is recoverable and never completed past deadline."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        f"{primary_url}&slowFrame=1",
        SnapshotLimits(total_timeout_ms=6_000),
    )

    delayed_frames = [
        frame
        for frame in observation.frames
        if frame.stop_reason == "deadline"
    ]
    assert delayed_frames, [(frame.name, frame.url) for frame in observation.frames]
    delayed_frame = delayed_frames[0]
    assert observation.deadline_reached is True
    assert delayed_frame.status != "completed"
    assert delayed_frame.stop_reason == "deadline"
    assert delayed_frame.errors
    assert all(error.recoverable for error in delayed_frame.errors)


def test_missing_browser_raises_safe_install_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing project-local Chromium gives safe, worktree-specific guidance."""
    project_root = tmp_path / "fixture-project"
    empty_browser_path = project_root / ".playwright-browsers"
    empty_browser_path.mkdir(parents=True)
    local_python = project_root / ".venv" / "Scripts" / "python.exe"
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(browser_module, "_project_root", lambda: project_root)
    secret_url = "http://127.0.0.1:9/?token=fixture-secret"

    with pytest.raises(BrowserUnavailableError) as exc_info:
        PlaywrightBrowserSource(headless=True).collect(secret_url, SnapshotLimits())

    message = str(exc_info.value)
    assert "-m playwright install chromium" in message
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(empty_browser_path)
    assert str(empty_browser_path) in message
    assert str(local_python) in message
    assert "PLAYWRIGHT_BROWSERS_PATH" in message
    assert secret_url not in message
    assert "fixture-secret" not in message
    assert "http://" not in message
    assert "https://" not in message


def test_server_cleanup_attempts_close_and_join_when_shutdown_fails() -> None:
    """A shutdown failure must not skip socket closure or thread joining."""

    class FailingServer:
        shutdown_called = False
        close_called = False

        def shutdown(self) -> None:
            self.shutdown_called = True
            raise RuntimeError("synthetic shutdown failure")

        def server_close(self) -> None:
            self.close_called = True

    class RecordingThread:
        join_called = False

        def join(self) -> None:
            self.join_called = True

    server = FailingServer()
    thread = RecordingThread()

    with pytest.raises(RuntimeError, match="synthetic shutdown failure"):
        fixture_support._stop_server(server, thread, started=True)

    assert server.shutdown_called is True
    assert server.close_called is True
    assert thread.join_called is True


def test_server_start_failure_closes_bound_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thread start failure closes the already-bound fixture socket."""

    class RecordingServer:
        server_port = 0
        close_called = False

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            self.close_called = True

    class FailingThread:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("synthetic start failure")

    server = RecordingServer()
    monkeypatch.setattr(fixture_support, "ThreadingHTTPServer", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(fixture_support, "Thread", FailingThread)

    with pytest.raises(RuntimeError, match="synthetic start failure"):
        fixture_support._serve(tmp_path)

    assert server.close_called is True
