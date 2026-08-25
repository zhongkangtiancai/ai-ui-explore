import pytest

from ai_ui_explorer.persistence.dtos import (
    PersistedComparisonIdentityMetadata,
    PersistencePayloadError,
    validate_safe_json_payload,
)


def test_persisted_comparison_identity_metadata_requires_matching_safe_labels() -> None:
    metadata = PersistedComparisonIdentityMetadata(
        schema_version="1.0",
        states={"identity-1": "completed", "identity-2": "partial"},
        labels={"identity-1": "管理员", "identity-2": "普通用户"},
    )

    assert metadata.labels["identity-1"] == "管理员"


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
