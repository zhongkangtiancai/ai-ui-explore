"""Tests for the versioned Application Manifest contract."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
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
    ("origin", "expected"),
    [
        ("https://例子.测试", "https://xn--fsqu00a.xn--0zwm56d"),
        (
            "https://[2001:0DB8:0:0:0:0:0:1]",
            "https://[2001:db8::1]",
        ),
        ("https://127.000.000.001", "https://127.0.0.1"),
        ("https://010.0.0.1", "https://8.0.0.1"),
    ],
)
def test_manifest_uses_browser_equivalent_host_serialization(
    origin: str,
    expected: str,
) -> None:
    manifest = ApplicationManifest(
        application_id="app",
        name="App",
        environment="test",
        allowed_origins=[origin],
    )

    assert manifest.allowed_origins == [expected]


@pytest.mark.parametrize(
    "origins",
    [
        ["https://例子.测试", "https://xn--fsqu00a.xn--0zwm56d"],
        [
            "https://[2001:0DB8:0:0:0:0:0:1]",
            "https://[2001:db8::1]",
        ],
        ["https://127.000.000.001", "https://127.0.0.1"],
    ],
)
def test_manifest_rejects_browser_equivalent_duplicate_origins(
    origins: list[str],
) -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id="app",
            name="App",
            environment="test",
            allowed_origins=origins,
        )


@pytest.mark.parametrize(
    ("target", "authentication"),
    [
        ("https://例子.测试", "https://xn--fsqu00a.xn--0zwm56d"),
        (
            "https://[2001:0DB8:0:0:0:0:0:1]",
            "https://[2001:db8::1]",
        ),
        ("https://127.000.000.001", "https://127.0.0.1"),
    ],
)
def test_manifest_rejects_browser_equivalent_origin_role_overlap(
    target: str,
    authentication: str,
) -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id="app",
            name="App",
            environment="test",
            allowed_origins=[target],
            authentication_origins=[authentication],
        )


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
        "https://bad_host.test",
        "https://999.0.0.1",
        "https://example.test?",
        "https://example.test#",
        "https://example.test/?",
        "https://example.test/#",
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


@pytest.mark.parametrize(
    ("declared", "visited"),
    [
        ("https://xn--fsqu00a.xn--0zwm56d", "https://例子.测试/path"),
        ("https://[2001:db8::1]", "https://[2001:0DB8:0:0:0:0:0:1]/path"),
        ("https://127.0.0.1", "https://127.000.000.001/path"),
    ],
)
def test_manifest_classification_reuses_browser_equivalent_origin(
    declared: str,
    visited: str,
) -> None:
    manifest = ApplicationManifest(
        application_id="app",
        name="App",
        environment="test",
        allowed_origins=[declared],
    )

    assert manifest.classify_url(visited) == "target"


def test_manifest_validation_error_does_not_echo_credentials() -> None:
    synthetic_password = "pw123"

    with pytest.raises(ValidationError) as captured:
        ApplicationManifest(
            application_id="app",
            name="App",
            environment="test",
            allowed_origins=[
                f"https://user:{synthetic_password}@example.test"
            ],
        )

    assert synthetic_password not in str(captured.value)


def test_manifest_is_frozen() -> None:
    manifest = ApplicationManifest(
        application_id="app",
        name="App",
        environment="test",
        allowed_origins=["https://example.test"],
    )

    with pytest.raises(ValidationError):
        manifest.name = "Changed"
    with pytest.raises(TypeError):
        manifest.allowed_origins.append("https://other.example.test")


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


def test_committed_manifest_schema_declares_draft_and_validates_structure() -> None:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "ai_ui_explorer"
        / "knowledge"
        / "schema"
        / "application-manifest-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    validator = Draft202012Validator(schema)
    valid_payload = ApplicationManifest(
        application_id="app",
        name="App",
        environment="test",
        allowed_origins=["https://example.test"],
    ).model_dump(mode="json")
    validator.validate(valid_payload)

    with pytest.raises(JsonSchemaValidationError):
        validator.validate({**valid_payload, "unexpected": True})
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({**valid_payload, "application_id": "Invalid_ID"})
