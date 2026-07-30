"""Tests for the versioned Application Manifest contract."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_ui_explorer.knowledge.manifest import ApplicationManifest


def test_manifest_normalizes_and_sorts_exact_origins() -> None:
    manifest = ApplicationManifest(
        application_id="customer-service-portal",
        name="客服管理平台",
        environment="test",
        allowed_origins=[
            "HTTPS://B.EXAMPLE.INTERNAL:443/",
            "https://a.example.internal",
        ],
        authentication_origins=["https://SSO.EXAMPLE.INTERNAL:8443/"],
    )

    assert manifest.allowed_origins == [
        "https://a.example.internal",
        "https://b.example.internal",
    ]
    assert manifest.authentication_origins == [
        "https://sso.example.internal:8443"
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@example.test",
        "https://example.test/path",
        "https://example.test?token=secret",
        "https://example.test/#fragment",
        "javascript:alert(1)",
        "ftp://example.test",
        "https:///missing-host",
    ],
)
def test_manifest_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id="app",
            name="App",
            environment="test",
            allowed_origins=[origin],
        )


@pytest.mark.parametrize(
    ("allowed", "authentication"),
    [
        (["https://example.test", "https://EXAMPLE.TEST:443/"], []),
        (
            ["https://example.test"],
            ["https://EXAMPLE.TEST:443/"],
        ),
    ],
)
def test_manifest_rejects_duplicate_or_overlapping_normalized_origins(
    allowed: list[str],
    authentication: list[str],
) -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id="app",
            name="App",
            environment="test",
            allowed_origins=allowed,
            authentication_origins=authentication,
        )


@pytest.mark.parametrize(
    "application_id",
    ["CustomerPortal", "-portal", "portal_name", "a" * 65],
)
def test_manifest_rejects_unsafe_application_ids(application_id: str) -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id=application_id,
            name="App",
            environment="test",
            allowed_origins=["https://example.test"],
        )


def test_manifest_rejects_blank_name_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id="app",
            name=" ",
            environment="test",
            allowed_origins=["https://example.test"],
        )

    with pytest.raises(ValidationError):
        ApplicationManifest.model_validate(
            {
                "application_id": "app",
                "name": "App",
                "environment": "test",
                "allowed_origins": ["https://example.test"],
                "secret": "must-not-be-accepted",
            }
        )


def test_manifest_classifies_by_exact_origin_without_downgrade_or_suffix_match() -> None:
    manifest = ApplicationManifest(
        application_id="app",
        name="App",
        environment="test",
        allowed_origins=["https://example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    assert manifest.classify_url("https://example.test/path?q=1") == "target"
    assert manifest.classify_url("https://sso.example.test/login") == "authentication"
    assert manifest.classify_url("https://example.test.evil.invalid/") == "outside"
    assert manifest.classify_url("http://example.test/") == "outside"


def test_manifest_is_frozen() -> None:
    manifest = ApplicationManifest(
        application_id="app",
        name="App",
        environment="test",
        allowed_origins=["https://example.test"],
    )

    with pytest.raises(ValidationError):
        manifest.name = "Changed"


def test_committed_manifest_schema_matches_model_schema() -> None:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "ai_ui_explorer"
        / "knowledge"
        / "schema"
        / "application-manifest-v1.schema.json"
    )
    committed = json.loads(schema_path.read_text(encoding="utf-8"))

    assert committed == ApplicationManifest.to_schema()
