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
)
def test_redactor_removes_sensitive_values(
    raw: str, secret: str, category: str
) -> None:
    result = Redactor().redact_text(raw)

    assert secret not in result.value
    assert f"[REDACTED:{category}]" in result.value
    assert result.count >= 1
    assert category in result.categories


def test_redactor_removes_sensitive_query_values() -> None:
    result = Redactor().redact_url(
        "https://example.test/path?token=secret&view=list#section"
    )

    assert "secret" not in result.value
    assert "token=%5BREDACTED%3ATOKEN%5D" in result.value
    assert "view=list" in result.value
    assert result.value.endswith("#section")
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
