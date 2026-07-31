"""Tests for the public Knowledge Package command-line interface."""

import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

import ai_ui_explorer.knowledge.cli as cli_module
from ai_ui_explorer.knowledge.cli import build_parser, main
from ai_ui_explorer.knowledge.models import KnowledgePackage
from tests.knowledge.factories import make_manifest
from tests.snapshot.factories import make_snapshot


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def test_cli_returns_zero_for_complete_package(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(manifest_path, make_manifest().model_dump(mode="json"))
    _write_json(snapshot_path, make_snapshot().model_dump(mode="json"))

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    output = output_dir / "knowledge-package.json"
    assert result == 0
    assert output.exists()
    package = KnowledgePackage.model_validate_json(
        output.read_text(encoding="utf-8")
    )
    assert package.status == "completed"


def test_cli_returns_two_for_budgeted_partial_package(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(manifest_path, make_manifest().model_dump(mode="json"))
    _write_json(snapshot_path, make_snapshot().model_dump(mode="json"))

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
            "--max-facts",
            "1",
        ]
    )

    package = KnowledgePackage.model_validate_json(
        (output_dir / "knowledge-package.json").read_text(encoding="utf-8")
    )
    assert result == 2
    assert package.status == "partial"


def test_cli_returns_two_when_knowledge_gap_budget_is_one(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(manifest_path, make_manifest().model_dump(mode="json"))
    _write_json(snapshot_path, make_snapshot().model_dump(mode="json"))

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
            "--max-knowledge-gaps",
            "1",
        ]
    )

    package = KnowledgePackage.model_validate_json(
        (output_dir / "knowledge-package.json").read_text(encoding="utf-8")
    )
    assert result == 2
    assert package.knowledge_gaps[0].reason_code == "collection_truncated"


def test_cli_returns_one_without_leaking_invalid_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "synthetic-secret"
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(
        manifest_path,
        {
            "application_id": "example-app",
            "name": "Example",
            "environment": "test",
            "allowed_origins": [f"https://user:{secret}@example.test"],
        },
    )
    _write_json(snapshot_path, make_snapshot().model_dump(mode="json"))

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert not (output_dir / "knowledge-package.json").exists()
    assert secret not in captured.out + captured.err


@pytest.mark.parametrize(
    "snapshot_payload",
    [
        {
            "schema_version": "synthetic-secret-version",
            "page_body": "synthetic-secret-body",
        },
        {
            **make_snapshot().model_dump(mode="json"),
            "page_body": "synthetic-secret-body",
        },
    ],
    ids=["unknown-version", "invalid-snapshot-body"],
)
def test_cli_rejects_invalid_snapshot_without_leaking_payload(
    snapshot_payload: dict[str, object],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(manifest_path, make_manifest().model_dump(mode="json"))
    _write_json(snapshot_path, snapshot_payload)

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "synthetic-secret" not in captured.out + captured.err
    assert not (output_dir / "knowledge-package.json").exists()


def test_cli_catches_schema_validation_without_leaking_instance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "schema-instance-secret"
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(manifest_path, make_manifest().model_dump(mode="json"))
    _write_json(snapshot_path, make_snapshot().model_dump(mode="json"))

    def fail_schema(*args: object, **kwargs: object) -> Path:
        raise JsonSchemaValidationError(f"invalid instance {secret}")

    monkeypatch.setattr(cli_module, "write_knowledge_package", fail_schema)

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert secret not in captured.out + captured.err
    assert not (output_dir / "knowledge-package.json").exists()


def test_cli_has_no_secret_arguments() -> None:
    help_text = build_parser().format_help().lower()

    assert "password" not in help_text
    assert "cookie" not in help_text
    assert "token" not in help_text


@pytest.mark.parametrize(
    ("option", "invalid_value"),
    [
        ("--max-evidence-chars", "0"),
        ("--max-evidence-chars", "10001"),
        ("--max-locators-per-element", "0"),
        ("--max-locators-per-element", "101"),
        ("--max-facts", "0"),
        ("--max-facts", "1000001"),
        ("--max-observations", "-1"),
        ("--max-observations", "10001"),
        ("--max-knowledge-gaps", "0"),
        ("--max-knowledge-gaps", "10001"),
        ("--max-json-bytes", "65535"),
        ("--max-json-bytes", "524288001"),
    ],
)
def test_cli_rejects_out_of_range_budget(
    option: str,
    invalid_value: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "manifest.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "knowledge"
    _write_json(manifest_path, make_manifest().model_dump(mode="json"))
    _write_json(snapshot_path, make_snapshot().model_dump(mode="json"))

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
            option,
            invalid_value,
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "validation error" not in captured.out + captured.err
    assert not (output_dir / "knowledge-package.json").exists()
