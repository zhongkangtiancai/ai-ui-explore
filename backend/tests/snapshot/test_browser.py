"""Real Chromium tests for initial page and frame observation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_ui_explorer.snapshot import browser as browser_module
from ai_ui_explorer.snapshot.browser import BrowserUnavailableError, PlaywrightBrowserSource
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
