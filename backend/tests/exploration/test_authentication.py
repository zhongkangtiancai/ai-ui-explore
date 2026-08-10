"""Authentication plan validation tests."""

import pytest
from pydantic import ValidationError

from ai_ui_explorer.exploration.authentication import (
    AuthenticationError,
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy


def test_plan_rejects_authentication_url_outside_authentication_origins() -> None:
    plan = AuthenticationPlan(
        authentication_url="https://outside.example.test/login",
        post_login_url_prefix="https://app.example.test/dashboard",
        checkpoint_css_selector="#signed-in-marker",
    )
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    with pytest.raises(AuthenticationError, match="Authentication plan denied"):
        plan.validate(policy)


def test_plan_rejects_post_login_prefix_outside_target_origin() -> None:
    plan = AuthenticationPlan(
        authentication_url="https://sso.example.test/login",
        post_login_url_prefix="https://sso.example.test/complete",
        checkpoint_css_selector="#signed-in-marker",
    )
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    with pytest.raises(AuthenticationError, match="Authentication plan denied"):
        plan.validate(policy)


def test_plan_accepts_explicit_authentication_and_target_origins() -> None:
    plan = AuthenticationPlan(
        authentication_url="https://sso.example.test/login",
        post_login_url_prefix="https://app.example.test/dashboard",
        checkpoint_css_selector="#signed-in-marker",
    )
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    plan.validate(policy)


def test_plan_denial_does_not_leak_configured_values() -> None:
    secret_url = "https://outside.example.test/login?token=secret"
    secret_selector = "#secret-selector"
    plan = AuthenticationPlan(
        authentication_url=secret_url,
        post_login_url_prefix="https://app.example.test/dashboard",
        checkpoint_css_selector=secret_selector,
    )
    policy = NavigationPolicy(allowed_origins=["https://app.example.test"])

    with pytest.raises(AuthenticationError) as error:
        plan.validate(policy)

    assert str(error.value) == "Authentication plan denied."
    assert secret_url not in str(error.value)
    assert secret_selector not in str(error.value)


def test_authentication_verification_is_immutable_and_validated() -> None:
    verification = AuthenticationVerification(
        authenticated=True,
        reason_code="verified",
        checkpoint_id="configured_post_login_checkpoint",
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        verification.authenticated = False  # type: ignore[misc]
