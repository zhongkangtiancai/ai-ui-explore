"""Deterministic tests for the human-assisted login runtime."""

from typing import cast

import pytest

from ai_ui_explorer.exploration import (
    AuthenticationPlan,
    AuthenticationVerification,
    ExplorationTask,
    ExplorationTaskState,
    HumanLoginRuntimeError,
    HumanLoginSession,
    NavigationPolicy,
)
from ai_ui_explorer.exploration.collector_adapter import (
    SessionSnapshotCollectorAdapter,
)
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession


class _FakeBrowser:
    def __init__(
        self,
        *,
        current_url: str = "https://app.example.test/dashboard",
        checkpoint_present: bool = True,
        goto_error: Exception | None = None,
        css_error: Exception | None = None,
    ) -> None:
        self.current_url = current_url
        self.checkpoint_present = checkpoint_present
        self.goto_error = goto_error
        self.css_error = css_error
        self.goto_calls: list[str] = []
        self.css_calls: list[str] = []
        self.close_calls = 0

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)
        if self.goto_error is not None:
            raise self.goto_error

    def has_css(self, selector: str) -> bool:
        self.css_calls.append(selector)
        if self.css_error is not None:
            raise self.css_error
        return self.checkpoint_present

    def close(self) -> None:
        self.close_calls += 1


class _FakeCollector:
    pass


def _plan() -> AuthenticationPlan:
    return AuthenticationPlan(
        authentication_url="https://sso.example.test/login",
        post_login_url_prefix="https://app.example.test/dashboard",
        checkpoint_css_selector="#signed-in-marker",
    )


def _policy() -> NavigationPolicy:
    return NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )


def _session(
    *,
    browser: _FakeBrowser | None = None,
    plan: AuthenticationPlan | None = None,
) -> tuple[
    HumanLoginSession,
    ExplorationTask,
    _FakeBrowser,
    _FakeCollector,
]:
    task = ExplorationTask.create(task_id="task-1")
    fake_browser = browser or _FakeBrowser()
    collector = _FakeCollector()
    session = HumanLoginSession(
        task=task,
        plan=plan or _plan(),
        policy=_policy(),
        browser=cast(PlaywrightBrowserSession, fake_browser),
        collector=cast(SessionSnapshotCollectorAdapter, collector),
    )
    return session, task, fake_browser, collector


def _started_session(
    *,
    browser: _FakeBrowser | None = None,
) -> tuple[
    HumanLoginSession,
    ExplorationTask,
    _FakeBrowser,
    _FakeCollector,
]:
    session, task, fake_browser, collector = _session(browser=browser)
    session.start()
    return session, task, fake_browser, collector


def test_collector_is_unavailable_before_authentication_is_verified() -> None:
    session, _, _, _ = _started_session()

    with pytest.raises(
        HumanLoginRuntimeError,
        match=r"^Authentication is not verified\.$",
    ):
        session.collector_port()


def test_start_validates_plan_navigates_and_pauses_for_human() -> None:
    session, task, browser, _ = _session()

    session.start()

    assert browser.goto_calls == ["https://sso.example.test/login"]
    assert task.state == ExplorationTaskState.PAUSED_FOR_HUMAN
    assert task.audit_events[-1].reason_code == "authentication_required"


def test_start_rejects_invalid_plan_before_navigation_with_safe_error() -> None:
    unsafe_url = "https://outside.example.test/login?token=secret"
    session, task, browser, _ = _session(
        plan=AuthenticationPlan(
            authentication_url=unsafe_url,
            post_login_url_prefix="https://app.example.test/dashboard",
            checkpoint_css_selector="#secret-selector",
        )
    )

    with pytest.raises(
        HumanLoginRuntimeError,
        match=r"^Human login session could not start\.$",
    ) as error:
        session.start()

    assert unsafe_url not in str(error.value)
    assert task.state == ExplorationTaskState.CREATED
    assert browser.goto_calls == []
    assert browser.close_calls == 1


def test_start_browser_failure_closes_session_without_leaking_detail() -> None:
    session, task, browser, _ = _session(
        browser=_FakeBrowser(goto_error=RuntimeError("token=secret"))
    )

    with pytest.raises(HumanLoginRuntimeError) as error:
        session.start()

    assert str(error.value) == "Human login session could not start."
    assert "secret" not in str(error.value)
    assert task.state == ExplorationTaskState.CANCELLED
    assert browser.close_calls == 1


def test_missing_checkpoint_returns_to_pause_without_checkpoint() -> None:
    browser = _FakeBrowser(checkpoint_present=False)
    session, task, _, _ = _started_session(browser=browser)

    verification = session.confirm_and_verify()

    assert verification == AuthenticationVerification(
        authenticated=False,
        reason_code="checkpoint_not_verified",
        checkpoint_id=None,
    )
    assert task.state == ExplorationTaskState.PAUSED_FOR_HUMAN
    assert task.checkpoint_id is None
    assert task.audit_events[-2].event_type == "human_confirmed"
    assert task.audit_events[-1].event_type == "authentication_rejected"


def test_post_login_prefix_is_checked_before_css() -> None:
    browser = _FakeBrowser(current_url="https://app.example.test/settings")
    session, task, _, _ = _started_session(browser=browser)

    verification = session.confirm_and_verify()

    assert verification.authenticated is False
    assert verification.checkpoint_id is None
    assert browser.css_calls == []
    assert task.state == ExplorationTaskState.PAUSED_FOR_HUMAN


def test_target_origin_is_checked_before_css() -> None:
    browser = _FakeBrowser(
        current_url="https://outside.example.test/dashboard?token=secret"
    )
    session, task, _, _ = _started_session(browser=browser)

    verification = session.confirm_and_verify()

    assert verification == AuthenticationVerification(
        authenticated=False,
        reason_code="checkpoint_not_verified",
        checkpoint_id=None,
    )
    assert browser.css_calls == []
    assert task.state == ExplorationTaskState.PAUSED_FOR_HUMAN


def test_successful_verification_resumes_and_exposes_bound_collector() -> None:
    session, task, browser, collector = _started_session()

    verification = session.confirm_and_verify()

    assert verification == AuthenticationVerification(
        authenticated=True,
        reason_code="verified",
        checkpoint_id="configured_post_login_checkpoint",
    )
    assert browser.css_calls == ["#signed-in-marker"]
    assert task.state == ExplorationTaskState.COLLECTING
    assert task.checkpoint_id == "configured_post_login_checkpoint"
    assert session.collector_port() is collector


def test_verification_exception_returns_safe_failure_and_stays_paused() -> None:
    browser = _FakeBrowser(css_error=RuntimeError("selector token=secret"))
    session, task, _, _ = _started_session(browser=browser)

    verification = session.confirm_and_verify()

    assert verification == AuthenticationVerification(
        authenticated=False,
        reason_code="checkpoint_not_verified",
        checkpoint_id=None,
    )
    assert "secret" not in repr(verification)
    assert task.state == ExplorationTaskState.PAUSED_FOR_HUMAN
    assert task.checkpoint_id is None


def test_close_is_idempotent_and_prevents_collection_or_verification() -> None:
    session, _, browser, _ = _started_session()
    session.confirm_and_verify()

    session.close()
    session.close()

    assert browser.close_calls == 1
    with pytest.raises(
        HumanLoginRuntimeError,
        match=r"^Authentication is not verified\.$",
    ):
        session.collector_port()
    with pytest.raises(
        HumanLoginRuntimeError,
        match=r"^Human login session is closed\.$",
    ):
        session.confirm_and_verify()
