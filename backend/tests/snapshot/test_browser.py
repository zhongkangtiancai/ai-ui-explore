"""Real Chromium tests for initial page and frame observation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_ui_explorer.snapshot.browser import BrowserUnavailableError, PlaywrightBrowserSource
from ai_ui_explorer.snapshot.models import SnapshotLimits


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
    assert all(frame.scroll_results == [] for frame in observation.frames)


def test_missing_browser_raises_safe_install_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing local Chromium gives actionable guidance without echoing the target URL."""
    empty_browser_path = tmp_path / "empty-browsers"
    empty_browser_path.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(empty_browser_path))
    secret_url = "http://127.0.0.1:9/?token=fixture-secret"

    with pytest.raises(BrowserUnavailableError) as exc_info:
        PlaywrightBrowserSource(headless=True).collect(secret_url, SnapshotLimits())

    message = str(exc_info.value)
    assert "python -m playwright install chromium" in message
    assert secret_url not in message
    assert "fixture-secret" not in message
    assert "http://" not in message
    assert "https://" not in message
