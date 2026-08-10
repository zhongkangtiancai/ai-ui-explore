"""Explicit authentication plan validation for human-assisted login."""

from pydantic import Field

from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel


class AuthenticationError(RuntimeError):
    """Safe authentication plan denial surface."""


class AuthenticationPlan(DeepFrozenModel):
    """Explicit, policy-bound configuration for a human authentication handoff."""

    authentication_url: str = Field(min_length=1, max_length=2_048)
    post_login_url_prefix: str = Field(min_length=1, max_length=2_048)
    checkpoint_css_selector: str = Field(min_length=1, max_length=512)

    def validate(  # type: ignore[override]
        self,
        policy: NavigationPolicy,
    ) -> None:
        """Reject plans whose handoff or verification URL is not policy-approved."""
        if not policy.evaluate(
            self.authentication_url,
            authentication_handoff=True,
        ).allowed:
            raise AuthenticationError("Authentication plan denied.")
        if not policy.evaluate(self.post_login_url_prefix).allowed:
            raise AuthenticationError("Authentication plan denied.")


class AuthenticationVerification(DeepFrozenModel):
    """Result of an explicit post-login checkpoint verification."""

    authenticated: bool
    reason_code: str = Field(min_length=1)
    checkpoint_id: str | None
