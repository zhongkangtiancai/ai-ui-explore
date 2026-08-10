"""Real Chromium acceptance tests for an in-memory browser session."""

from collections.abc import Callable
from typing import cast

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from playwright.sync_api import Error as PlaywrightError

from ai_ui_explorer.exploration import (
    AuthenticationPlan,
    ExplorationBudget,
    ExplorationRunner,
    ExplorationTask,
    ExplorationTaskState,
    HumanLoginRuntimeError,
    HumanLoginSession,
    ModuleEntry,
    NavigationCandidate,
)
from ai_ui_explorer.exploration.collector_adapter import (
    SessionSnapshotCollectorAdapter,
)
from ai_ui_explorer.snapshot.browser import (
    PlaywrightBrowserSession,
    RawPageObservation,
)
from ai_ui_explorer.snapshot.collector import CollectionFailedError, SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotLimits
from tests.snapshot.conftest import LoginSite


def _fixture_page(session: PlaywrightBrowserSession) -> Page:
    return cast(Page, object.__getattribute__(session, "_page"))


def _browser_session(runtime: HumanLoginSession) -> PlaywrightBrowserSession:
    return cast(
        PlaywrightBrowserSession,
        object.__getattribute__(runtime, "_browser"),
    )


def _browser_session_is_closed(session: PlaywrightBrowserSession) -> bool:
    return cast(bool, object.__getattribute__(session, "_closed"))


def _make_browser_runtime(
    login_site: LoginSite,
    *,
    first_terminal_callback: Callable[[], None] | None = None,
) -> tuple[HumanLoginSession, ExplorationTask, PlaywrightBrowserSession]:
    browser = PlaywrightBrowserSession.open(headless=False)
    task = ExplorationTask.create(task_id="fixture-human-login")
    if first_terminal_callback is not None:
        task.register_terminal_callback(first_terminal_callback)
    runtime = HumanLoginSession(
        task=task,
        plan=AuthenticationPlan(
            authentication_url=login_site.login_url,
            post_login_url_prefix=login_site.dashboard_url,
            checkpoint_css_selector="#signed-in-marker",
        ),
        policy=login_site.policy,
        browser=browser,
        collector=SessionSnapshotCollectorAdapter(
            session=browser,
            task=task,
            limits=SnapshotLimits(),
        ),
    )
    return runtime, task, browser


def _simulate_human_login(runtime: HumanLoginSession) -> None:
    session = _browser_session(runtime)
    _fixture_page(session).locator("#fixture-login").click()


def test_human_login_runtime_resumes_controlled_exploration(
    login_site: LoginSite,
) -> None:
    runtime, task, browser = _make_browser_runtime(login_site)
    try:
        assert browser.is_headless is False
        runtime.start()
        _simulate_human_login(runtime)

        assert runtime.confirm_and_verify().authenticated is True

        result = ExplorationRunner(
            policy=login_site.policy,
            budget=ExplorationBudget(
                max_pages=1,
                max_depth=0,
                max_queue_size=1,
            ),
            collector=runtime.collector_port(),
            task=task,
        ).run(
            modules=[
                ModuleEntry(
                    module_id="dashboard",
                    url=login_site.dashboard_url,
                )
            ]
        )

        assert result.status == "completed"
        assert len(result.visits) == 1
        assert task.state == ExplorationTaskState.COMPLETED
        assert _browser_session_is_closed(browser) is True
        with pytest.raises(
            HumanLoginRuntimeError,
            match=r"^Authentication is not verified\.$",
        ):
            runtime.collector_port()
    finally:
        runtime.close()


def test_human_login_runtime_closes_browser_when_runner_raises(
    login_site: LoginSite,
) -> None:
    callback_calls: list[str] = []

    def fail_first_terminal_callback() -> None:
        callback_calls.append("failing_callback")
        raise RuntimeError("fixture cleanup failure token=secret")

    runtime, task, browser = _make_browser_runtime(
        login_site,
        first_terminal_callback=fail_first_terminal_callback,
    )

    def fail_candidate_extraction(
        _snapshot: SnapshotDocument,
    ) -> list[NavigationCandidate]:
        raise RuntimeError("fixture candidate failure")

    try:
        runtime.start()
        _simulate_human_login(runtime)
        assert runtime.confirm_and_verify().authenticated is True

        with pytest.raises(RuntimeError, match="fixture candidate failure"):
            ExplorationRunner(
                policy=login_site.policy,
                budget=ExplorationBudget(
                    max_pages=1,
                    max_depth=0,
                    max_queue_size=1,
                ),
                collector=runtime.collector_port(),
                candidate_extractor=fail_candidate_extraction,
                task=task,
            ).run(
                modules=[
                    ModuleEntry(
                        module_id="dashboard",
                        url=login_site.dashboard_url,
                    )
                ]
            )

        assert task.state == ExplorationTaskState.FAILED
        assert callback_calls == ["failing_callback"]
        assert _browser_session_is_closed(browser) is True
    finally:
        runtime.close()


def test_session_collector_observes_login_only_dashboard(login_site: LoginSite) -> None:
    session = PlaywrightBrowserSession.open(headless=True)
    try:
        session.goto(login_site.login_url)
        _fixture_page(session).locator("#fixture-login").click()
        snapshot = SessionSnapshotCollectorAdapter(
            session=session,
            task=ExplorationTask.create(task_id="fixture-collector"),
            limits=SnapshotLimits(),
        ).collect(login_site.dashboard_url)
    finally:
        session.close()

    assert snapshot.source.final_url == login_site.dashboard_url
    assert any(
        element.attributes.get("id") == "signed-in-marker"
        for frame in snapshot.frames
        for element in frame.elements
    )


def test_browser_session_close_is_idempotent() -> None:
    session = PlaywrightBrowserSession.open(headless=True)

    session.close()
    session.close()


def test_browser_session_public_api_does_not_expose_automation_objects() -> None:
    session = PlaywrightBrowserSession.open(headless=True)
    try:
        public_values = [
            getattr(session, name)
            for name in dir(session)
            if not name.startswith("_")
        ]
    finally:
        session.close()

    assert not any(
        isinstance(value, Page | BrowserContext)
        for value in public_values
    )


def test_browser_session_exposes_requested_headless_mode() -> None:
    closed: list[str] = []
    session = PlaywrightBrowserSession(
        playwright=cast(
            Playwright,
            _StoppingResource("playwright", closed, fail=False),
        ),
        browser=cast(
            Browser,
            _ClosingResource("browser", closed, fail=False),
        ),
        context=cast(
            BrowserContext,
            _ClosingResource("context", closed, fail=False),
        ),
        page=cast(Page, _ClosingResource("page", closed, fail=False)),
        headless=True,
    )

    assert session.is_headless is True
    session.close()


@pytest.mark.parametrize(
    "failing_step",
    [None, "page", "context", "browser", "playwright"],
)
def test_browser_session_close_continues_in_order_after_playwright_error(
    failing_step: str | None,
) -> None:
    closed: list[str] = []
    session = PlaywrightBrowserSession(
        playwright=cast(
            Playwright,
            _StoppingResource("playwright", closed, fail=failing_step == "playwright"),
        ),
        browser=cast(
            Browser,
            _ClosingResource("browser", closed, fail=failing_step == "browser"),
        ),
        context=cast(
            BrowserContext,
            _ClosingResource("context", closed, fail=failing_step == "context"),
        ),
        page=cast(
            Page,
            _ClosingResource("page", closed, fail=failing_step == "page"),
        ),
        headless=True,
    )

    session.close()
    session.close()

    assert closed == ["page", "context", "browser", "playwright"]


def test_browser_session_reports_current_page_and_css_presence(login_site: LoginSite) -> None:
    session = PlaywrightBrowserSession.open(headless=True)
    try:
        session.goto(login_site.login_url)

        assert session.current_url == login_site.login_url
        assert session.has_css("#fixture-login") is True
        assert session.has_css("#signed-in-marker") is False
    finally:
        session.close()


def test_session_collection_reuses_the_existing_page(login_site: LoginSite) -> None:
    session = PlaywrightBrowserSession.open(headless=True)
    try:
        session.goto(login_site.login_url)
        original_page = _fixture_page(session)
        created_pages: list[Page] = []

        def record_created_page(page: Page) -> None:
            created_pages.append(page)

        original_page.context.on("page", record_created_page)

        session.collect(login_site.login_url, SnapshotLimits())

        assert _fixture_page(session) is original_page
        assert created_pages == []
    finally:
        session.close()


def test_session_snapshot_does_not_expose_fixture_authentication_marker(
    login_site: LoginSite,
) -> None:
    session = PlaywrightBrowserSession.open(headless=True)
    try:
        session.goto(login_site.login_url)
        _fixture_page(session).locator("#fixture-login").click()
        snapshot = SessionSnapshotCollectorAdapter(
            session=session,
            task=ExplorationTask.create(task_id="fixture-collector"),
            limits=SnapshotLimits(),
        ).collect(login_site.dashboard_url)
    finally:
        session.close()

    fixture_marker = "fixture_authenticated=1"
    assert fixture_marker not in repr(snapshot)
    assert fixture_marker not in snapshot.model_dump_json()


class _FailingObservationSource:
    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        raise RuntimeError("unsafe upstream detail")


class _ClosingResource:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail: bool,
    ) -> None:
        self._name = name
        self._events = events
        self._fail = fail

    def close(self) -> None:
        self._events.append(self._name)
        if self._fail:
            raise PlaywrightError("fixture close failure")


class _StoppingResource:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail: bool,
    ) -> None:
        self._name = name
        self._events = events
        self._fail = fail

    def stop(self) -> None:
        self._events.append(self._name)
        if self._fail:
            raise PlaywrightError("fixture close failure")


def test_session_collector_adapter_uses_fixed_collection_error() -> None:
    source = _FailingObservationSource()
    adapter = SessionSnapshotCollectorAdapter(
        session=cast(PlaywrightBrowserSession, source),
        task=ExplorationTask.create(task_id="fixture-collector"),
        limits=SnapshotLimits(),
    )

    with pytest.raises(
        CollectionFailedError,
        match=r"^Controlled exploration snapshot collection failed\.$",
    ):
        adapter.collect("https://app.example.test/dashboard")


def test_session_collector_adapter_rejects_collector_bound_to_other_session() -> None:
    session = cast(PlaywrightBrowserSession, _FailingObservationSource())
    other_session = _FailingObservationSource()

    with pytest.raises(
        ValueError,
        match=r"^Session collector source does not match browser session\.$",
    ):
        SessionSnapshotCollectorAdapter(
            session=session,
            task=ExplorationTask.create(task_id="fixture-collector"),
            collector=SnapshotCollector(source=other_session),
            limits=SnapshotLimits(),
        )


def test_session_collector_adapter_keeps_binding_checks_private() -> None:
    session = cast(PlaywrightBrowserSession, _FailingObservationSource())
    task = ExplorationTask.create(task_id="task-1")

    adapter = SessionSnapshotCollectorAdapter(
        session=session,
        task=task,
        limits=SnapshotLimits(),
    )

    public_names = {name for name in dir(adapter) if not name.startswith("_")}
    assert "is_bound_to" not in public_names
    assert "is_bound_to_task" not in public_names
