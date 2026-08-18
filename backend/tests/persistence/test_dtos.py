import pytest

from ai_ui_explorer.persistence.dtos import (
    PersistencePayloadError,
    validate_safe_json_payload,
)


def test_safe_json_payload_rejects_nested_sensitive_key() -> None:
    payload = {
        "schema_version": "1.0",
        "pages": [{"evidence": {"cookie": "must-not-persist"}}],
    }

    with pytest.raises(PersistencePayloadError, match="Persistence payload rejected"):
        validate_safe_json_payload(payload, allowed_schema_versions={"1.0"})


def test_safe_json_payload_rejects_unknown_future_schema_version() -> None:
    with pytest.raises(PersistencePayloadError, match="Persistence payload rejected"):
        validate_safe_json_payload(
            {"schema_version": "9.0", "pages": []},
            allowed_schema_versions={"1.0"},
        )


def test_safe_json_payload_returns_json_compatible_copy() -> None:
    payload = {"schema_version": "1.0", "pages": [{"page_id": "page-1"}]}

    persisted = validate_safe_json_payload(payload, allowed_schema_versions={"1.0"})

    assert persisted == payload
    assert persisted is not payload
