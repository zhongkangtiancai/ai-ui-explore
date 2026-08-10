"""In-memory orchestration for explicit human-assisted authentication."""

from ai_ui_explorer.exploration.authentication import (
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.collector_adapter import (
    SessionSnapshotCollectorAdapter,
    _session_collector_matches_binding,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.runner import SnapshotCollectorPort
from ai_ui_explorer.exploration.task import ExplorationTask
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession

_CHECKPOINT_ID = "configured_post_login_checkpoint"
_FAILED_REASON = "checkpoint_not_verified"


class HumanLoginRuntimeError(Exception):
    """Fixed, non-sensitive human login runtime error surface."""


class HumanLoginSession:
    """Coordinate one process-local browser session with explicit confirmation."""

    def __init__(
        self,
        task: ExplorationTask,
        plan: AuthenticationPlan,
        policy: NavigationPolicy,
        browser: PlaywrightBrowserSession,
        collector: SessionSnapshotCollectorAdapter,
    ) -> None:
        if not _session_collector_matches_binding(
            collector,
            session=browser,
            task=task,
        ):
            raise HumanLoginRuntimeError(
                "Session collector binding is invalid."
            )
        self._task = task
        self._plan = plan
        self._policy = policy
        self._browser = browser
        self._collector = collector
        self._verification: AuthenticationVerification | None = None
        self._closed = False
        self._task.register_terminal_callback(self.close)

    def start(self) -> None:
        """Validate the plan, open its handoff URL, and pause for the human."""
        self._require_open()
        if self._browser.is_headless:
            self._close_after_failure()
            raise HumanLoginRuntimeError(
                "Human login session requires a visible browser."
            )
        collection_started = False
        try:
            self._plan.validate(self._policy)
            self._task.start_collection()
            collection_started = True
            self._browser.goto(self._plan.authentication_url)
            self._task.pause_for_human(reason_code="authentication_required")
        except Exception:
            if collection_started:
                self._cancel_after_start_failure()
            self._close_after_failure()
            raise HumanLoginRuntimeError(
                "Human login session could not start."
            ) from None

    def confirm_and_verify(self) -> AuthenticationVerification:
        """Confirm the handoff and verify target URL then configured checkpoint."""
        self._require_open()
        try:
            self._task.confirm_human_ready()
        except Exception:
            raise HumanLoginRuntimeError(
                "Authentication cannot be verified."
            ) from None

        try:
            current_decision = self._policy.evaluate(self._browser.current_url)
            if not current_decision.allowed or current_decision.normalized_url is None:
                return self._reject_verification()

            prefix_decision = self._policy.evaluate(self._plan.post_login_url_prefix)
            if (
                not prefix_decision.allowed
                or prefix_decision.normalized_url is None
                or not current_decision.normalized_url.startswith(
                    prefix_decision.normalized_url
                )
            ):
                return self._reject_verification()

            if not self._browser.has_css(self._plan.checkpoint_css_selector):
                return self._reject_verification()
        except Exception:
            return self._reject_verification()

        verification = AuthenticationVerification(
            authenticated=True,
            reason_code="verified",
            checkpoint_id=_CHECKPOINT_ID,
        )
        self._task.record_authentication_result(
            authenticated=True,
            checkpoint_id=_CHECKPOINT_ID,
        )
        self._verification = verification
        return verification

    def collector_port(self) -> SnapshotCollectorPort:
        """Expose the bound collector only after successful verification."""
        if self._closed or self._verification is None:
            raise HumanLoginRuntimeError("Authentication is not verified.")
        return self._collector

    def close(self) -> None:
        """Idempotently destroy the process-local browser session."""
        if self._closed:
            return
        self._closed = True
        self._verification = None
        try:
            self._browser.close()
        except Exception:
            raise HumanLoginRuntimeError(
                "Human login session could not close."
            ) from None

    def _reject_verification(self) -> AuthenticationVerification:
        self._task.record_authentication_result(
            authenticated=False,
            checkpoint_id=None,
        )
        return AuthenticationVerification(
            authenticated=False,
            reason_code=_FAILED_REASON,
            checkpoint_id=None,
        )

    def _cancel_after_start_failure(self) -> None:
        try:
            self._task.cancel(reason_code="login_runtime_error")
        except Exception:
            pass

    def _close_after_failure(self) -> None:
        try:
            self.close()
        except HumanLoginRuntimeError:
            pass

    def _require_open(self) -> None:
        if self._closed:
            raise HumanLoginRuntimeError("Human login session is closed.")
