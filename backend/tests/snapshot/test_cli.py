"""Tests for the public snapshot collection command-line interface."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_ui_explorer.snapshot.cli import build_parser, main
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotLimits

from .factories import make_snapshot

_SNAPSHOT_SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "ai_ui_explorer"
    / "snapshot"
    / "schema"
    / "snapshot-v1.schema.json"
)


class FakeCollector:
    """Return a supplied snapshot without starting a browser."""

    def __init__(self, snapshot: SnapshotDocument) -> None:
        self._snapshot = snapshot

    def collect(self, url: str, limits: SnapshotLimits) -> SnapshotDocument:
        return self._snapshot


def test_cli_returns_zero_for_complete_snapshot(tmp_path: Path) -> None:
    collector = FakeCollector(make_snapshot())

    result = main(
        ["--url", "https://example.test", "--output", str(tmp_path)],
        collector_factory=lambda headed: collector,
    )

    assert result == 0
    assert (tmp_path / "snapshot.json").exists()


def test_cli_returns_two_for_partial_snapshot(tmp_path: Path) -> None:
    collector = FakeCollector(make_snapshot(status="partial", truncated=True))

    result = main(
        ["--url", "https://example.test", "--output", str(tmp_path)],
        collector_factory=lambda headed: collector,
    )

    assert result == 2


def test_cli_has_no_secret_arguments() -> None:
    help_text = build_parser().format_help().lower()

    assert "password" not in help_text
    assert "cookie" not in help_text
    assert "token" not in help_text


def test_cli_returns_one_without_printing_raw_collection_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingCollector:
        def collect(self, url: str, limits: SnapshotLimits) -> SnapshotDocument:
            raise RuntimeError("synthetic secret failure")

    result = main(
        ["--url", "https://example.test", "--output", str(tmp_path)],
        collector_factory=lambda headed: FailingCollector(),
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "synthetic secret failure" not in captured.out + captured.err


def test_cli_rejects_non_http_url_without_echoing_it(capsys: pytest.CaptureFixture[str]) -> None:
    unsafe_url = "file:///fixture-secret"

    result = main(["--url", unsafe_url, "--output", "output"])

    captured = capsys.readouterr()
    assert result == 2
    assert unsafe_url not in captured.out + captured.err


def test_real_cli_collects_fixture(
    primary_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["--url", primary_url, "--output", str(tmp_path)])

    output_path = tmp_path / "snapshot.json"
    serialized = output_path.read_text(encoding="utf-8")
    SnapshotDocument.model_validate(json.loads(serialized))
    schema = json.loads(_SNAPSHOT_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(serialized))
    captured = capsys.readouterr()

    assert result in {0, 2}
    assert output_path.exists()
    assert all(
        secret not in serialized + captured.out + captured.err
        for secret in (
            "fixture-password-do-not-return",
            "fixture-hidden-do-not-return",
            "fixture-scroll-secret-do-not-return",
        )
    )
