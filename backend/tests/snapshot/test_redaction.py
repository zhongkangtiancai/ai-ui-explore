import pytest

from ai_ui_explorer.snapshot.redaction import Redactor


@pytest.mark.parametrize(
    ("raw", "secret", "category"),
    [
        ("password=hunter2", "hunter2", "PASSWORD"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi", "TOKEN"),
        ("身份证 11010519491231002X", "11010519491231002X", "CHINESE_ID"),
        ("银行卡 6222021001112223333", "6222021001112223333", "BANK_CARD"),
        ("手机号 13800138000", "13800138000", "MOBILE"),
        ("邮箱 demo@example.com", "demo@example.com", "EMAIL"),
    ],
    ids=["password", "authorization", "chinese-id", "bank-card", "mobile", "email"],
)
def test_redactor_removes_sensitive_values(
    raw: str, secret: str, category: str
) -> None:
    __tracebackhide__ = True
    result = Redactor().redact_text(raw)

    count = result.count
    assert count >= 1
    assert category in result.categories
    assert f"[REDACTED:{category}]" in result.value
    contains_secret = secret in result.value
    assert not contains_secret


def test_redactor_removes_sensitive_query_values() -> None:
    result = Redactor().redact_url(
        "https://example.test/path?token=secret&view=list#section"
    )

    assert "secret" not in result.value
    assert "token=%5BREDACTED%3ATOKEN%5D" in result.value
    assert "view=list" in result.value
    assert "#" not in result.value
    assert result.count == 1
    assert result.categories == frozenset({"TOKEN"})


def test_redactor_drops_url_userinfo_and_preserves_non_sensitive_query_values() -> None:
    result = Redactor().redact_url(
        "https://user:pass@example.test/path?view=list&tab=details"
    )

    assert result.value == "https://example.test/path?view=list&tab=details"
    assert result.count == 1
    assert result.categories == frozenset({"URL_USERINFO"})


def test_redactor_does_not_return_the_original_url_when_parsing_fails() -> None:
    raw = "https://example.test:not-a-port/path"

    result = Redactor().redact_url(raw)

    assert result.value == "[REDACTED:URL]"
    assert result.count == 1
    assert result.categories == frozenset({"URL"})


def test_redactor_redacts_mapping_and_combines_summary() -> None:
    redacted, summary = Redactor().redact_mapping(
        {"email": "demo@example.com", "label": "Safe label"}
    )

    assert redacted == {"email": "[REDACTED:EMAIL]", "label": "Safe label"}
    assert summary.count == 1
    assert summary.categories == frozenset({"EMAIL"})


def test_redactor_redacts_mapping_values_for_sensitive_keys() -> None:
    redacted, summary = Redactor().redact_mapping(
        {"password": "hunter2", "label": "Safe label"}
    )

    assert redacted == {"password": "[REDACTED:PASSWORD]", "label": "Safe label"}
    assert summary.count == 1
    assert summary.categories == frozenset({"PASSWORD"})


def test_redactor_uses_text_rules_for_error_messages() -> None:
    result = Redactor().redact_error("request failed: api_key=sample-key")

    assert "sample-key" not in result.value
    assert result.value == "request failed: api_key=[REDACTED:API_KEY]"
    assert result.count == 1
    assert result.categories == frozenset({"API_KEY"})


def test_redactor_replaces_content_bearing_data_urls() -> None:
    result = Redactor().redact_url("data:text/html,<h1>private page</h1>")

    count = result.count
    assert count == 1
    assert result.categories == frozenset({"URL"})
    assert result.value == "[REDACTED:URL]"


@pytest.mark.parametrize(
    ("fragment", "secret", "category"),
    [
        ("access_token=fragment-secret", "fragment-secret", "TOKEN"),
        ("password=fragment-password", "fragment-password", "PASSWORD"),
    ],
    ids=["access-token", "password"],
)
def test_redactor_drops_sensitive_url_fragments(
    fragment: str, secret: str, category: str
) -> None:
    __tracebackhide__ = True
    result = Redactor().redact_url(f"https://example.test/callback#{fragment}")

    count = result.count
    assert count == 1
    assert result.categories == frozenset({category})
    assert "#" not in result.value
    contains_secret = secret in result.value
    assert not contains_secret


@pytest.mark.parametrize(
    ("raw", "secret", "category"),
    [
        ('{"password": "quoted-password"}', "quoted-password", "PASSWORD"),
        ("{'secret': 'quoted-secret'}", "quoted-secret", "SECRET"),
        ('{"api_key": "quoted-api-key"}', "quoted-api-key", "API_KEY"),
        (
            '{"authorization": "Bearer quoted.authorization.token"}',
            "quoted.authorization.token",
            "TOKEN",
        ),
    ],
    ids=["password", "secret", "api-key", "authorization"],
)
def test_redactor_redacts_quoted_sensitive_text_keys(
    raw: str, secret: str, category: str
) -> None:
    __tracebackhide__ = True
    result = Redactor().redact_text(raw)

    count = result.count
    assert count == 1
    assert result.categories == frozenset({category})
    contains_secret = secret in result.value
    assert not contains_secret


@pytest.mark.parametrize(
    ("raw", "secret", "category"),
    [
        ('request failed: {"password": "error-password"}', "error-password", "PASSWORD"),
        ("request failed: {'secret': 'error-secret'}", "error-secret", "SECRET"),
        ('request failed: {"api_key": "error-api-key"}', "error-api-key", "API_KEY"),
        (
            'request failed: {"authorization": "Bearer error.authorization.token"}',
            "error.authorization.token",
            "TOKEN",
        ),
    ],
    ids=["password", "secret", "api-key", "authorization"],
)
def test_redactor_redacts_quoted_sensitive_error_keys(
    raw: str, secret: str, category: str
) -> None:
    __tracebackhide__ = True
    result = Redactor().redact_error(raw)

    count = result.count
    assert count == 1
    assert result.categories == frozenset({category})
    contains_secret = secret in result.value
    assert not contains_secret


def test_redactor_redacts_oauth_query_parameters() -> None:
    result = Redactor().redact_url(
        "https://example.test/callback?access_token=query-access&refresh_token=query-refresh"
        "&id_token=query-id&view=list"
    )

    count = result.count
    assert count == 3
    assert result.categories == frozenset({"TOKEN"})
    assert "view=list" in result.value
    assert "query-access" not in result.value
    assert "query-refresh" not in result.value
    assert "query-id" not in result.value


def test_redactor_preserves_brackets_when_rebuilding_ipv6_urls() -> None:
    result = Redactor().redact_url("https://[2001:db8::1]:8443/path?view=list")

    assert result.count == 0
    assert result.value == "https://[2001:db8::1]:8443/path?view=list"
