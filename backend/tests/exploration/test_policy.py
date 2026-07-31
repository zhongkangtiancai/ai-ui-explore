"""Sprint 4 risk gate tests for controlled exploration."""

import pytest

from ai_ui_explorer.exploration.policy import (
    ActionGate,
    CandidateAction,
    NavigationPolicy,
    NavigationPolicyViolation,
)


def test_navigation_policy_allows_exact_target_origin() -> None:
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    decision = policy.evaluate("https://app.example.test/dashboard?token=secret")

    assert decision.allowed is True
    assert decision.normalized_url == "https://app.example.test/dashboard?token=secret"
    assert decision.origin == "https://app.example.test"
    assert decision.reason_code == "allowed_origin"


def test_navigation_policy_rejects_implicit_subdomains() -> None:
    policy = NavigationPolicy(allowed_origins=["https://example.test"])

    decision = policy.evaluate("https://admin.example.test/")

    assert decision.allowed is False
    assert decision.reason_code == "origin_not_allowed"
    assert "admin.example.test" not in decision.safe_message


def test_navigation_policy_rejects_userinfo_without_leaking_secret() -> None:
    policy = NavigationPolicy(allowed_origins=["https://example.test"])

    decision = policy.evaluate("https://secret@example.test/dashboard")

    assert decision.allowed is False
    assert decision.reason_code == "userinfo_not_allowed"
    assert "secret" not in decision.safe_message


def test_navigation_policy_requires_https_except_explicit_local_http() -> None:
    secure_policy = NavigationPolicy(allowed_origins=["http://example.test"])
    local_policy = NavigationPolicy(
        allowed_origins=["http://127.0.0.1:9000"],
        allow_local_http=True,
    )

    assert secure_policy.evaluate("http://example.test/").reason_code == "https_required"
    assert local_policy.evaluate("http://127.0.0.1:9000/").allowed is True


def test_navigation_policy_allows_auth_origin_only_during_handoff() -> None:
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    assert policy.evaluate("https://sso.example.test/login").allowed is False
    assert (
        policy.evaluate(
            "https://sso.example.test/login",
            authentication_handoff=True,
        ).reason_code
        == "authentication_origin"
    )


def test_assert_allowed_raises_safe_error() -> None:
    policy = NavigationPolicy(allowed_origins=["https://example.test"])

    with pytest.raises(NavigationPolicyViolation, match="Navigation denied"):
        policy.assert_allowed("https://outside.test/?token=secret")


def test_action_gate_allows_only_readonly_navigation() -> None:
    gate = ActionGate()

    assert gate.evaluate(CandidateAction(action_type="link_navigation")).allowed is True
    assert gate.evaluate(CandidateAction(action_type="browser_back")).allowed is True
    assert gate.evaluate(CandidateAction(action_type="module_entry")).allowed is True
    assert gate.evaluate(CandidateAction(action_type="button_click")).allowed is False
    assert gate.evaluate(CandidateAction(action_type="form_submit")).reason_code == "denied"
