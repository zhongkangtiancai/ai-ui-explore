"""Tests for the public snapshot collection command-line interface."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_ui_explorer.snapshot.cli import build_parser, main
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotDocumentV1, SnapshotLimits

from .factories import make_legacy_snapshot, make_snapshot

_SNAPSHOT_V1_1_SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "ai_ui_explorer"
    / "snapshot"
    / "schema"
    / "snapshot-v1.1.schema.json"
)
_SNAPSHOT_V1_SCHEMA_PATH = _SNAPSHOT_V1_1_SCHEMA_PATH.with_name("snapshot-v1.schema.json")
_RUNTIME_FIELDS = frozenset(
    {
        "snapshot_id",
        "started_at",
        "completed_at",
        "occurred_at",
        "duration_ms",
    }
)


class FakeCollector:
    """Return a supplied snapshot without starting a browser."""

    def __init__(self, snapshot: SnapshotDocument) -> None:
        self._snapshot = snapshot
        self.collect_calls = 0
        self.last_limits: SnapshotLimits | None = None

    def collect(self, url: str, limits: SnapshotLimits) -> SnapshotDocument:
        self.collect_calls += 1
        self.last_limits = limits
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


@pytest.mark.parametrize(
    ("option", "invalid_value"),
    [
        ("--timeout-ms", "not-a-number-secret"),
        ("--timeout-ms", "999"),
        ("--timeout-ms", "600001"),
        ("--max-frames", "not-a-number-secret"),
        ("--max-frames", "0"),
        ("--max-frames", "501"),
        ("--max-scroll-containers-per-frame", "not-a-number-secret"),
        ("--max-scroll-containers-per-frame", "-1"),
        ("--max-scroll-containers-per-frame", "201"),
        ("--max-scroll-rounds-per-container", "not-a-number-secret"),
        ("--max-scroll-rounds-per-container", "-1"),
        ("--max-scroll-rounds-per-container", "501"),
        ("--max-elements", "not-a-number-secret"),
        ("--max-elements", "0"),
        ("--max-elements", "100001"),
        ("--max-text-chars", "not-a-number-secret"),
        ("--max-text-chars", "-1"),
        ("--max-text-chars", "10001"),
        ("--max-json-bytes", "not-a-number-secret"),
        ("--max-json-bytes", "65535"),
        ("--max-json-bytes", "104857601"),
    ],
)
def test_cli_rejects_invalid_numeric_budget_as_safe_usage_error(
    option: str,
    invalid_value: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collector = FakeCollector(make_snapshot())
    unsafe_url = "https://user:fixture-secret@example.test/page"

    result = main(
        [
            "--url",
            unsafe_url,
            "--output",
            str(tmp_path),
            option,
            invalid_value,
        ],
        collector_factory=lambda headed: collector,
    )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert result == 2
    assert collector.collect_calls == 0
    assert not (tmp_path / "snapshot.json").exists()
    assert unsafe_url not in output
    assert "fixture-secret" not in output
    assert "not-a-number-secret" not in output
    assert "validation error" not in output.lower()
    assert "status=fatal" not in output


@pytest.mark.parametrize(
    ("option", "field_name", "boundary"),
    [
        ("--timeout-ms", "total_timeout_ms", 1_000),
        ("--timeout-ms", "total_timeout_ms", 600_000),
        ("--max-frames", "max_frames", 1),
        ("--max-frames", "max_frames", 500),
        ("--max-scroll-containers-per-frame", "max_scroll_containers_per_frame", 0),
        ("--max-scroll-containers-per-frame", "max_scroll_containers_per_frame", 200),
        ("--max-scroll-rounds-per-container", "max_scroll_rounds_per_container", 0),
        ("--max-scroll-rounds-per-container", "max_scroll_rounds_per_container", 500),
        ("--max-elements", "max_elements", 1),
        ("--max-elements", "max_elements", 100_000),
        ("--max-text-chars", "max_text_chars", 0),
        ("--max-text-chars", "max_text_chars", 10_000),
        ("--max-json-bytes", "max_json_bytes", 65_536),
        ("--max-json-bytes", "max_json_bytes", 100 * 1024 * 1024),
    ],
)
def test_cli_accepts_each_numeric_budget_boundary(
    option: str,
    field_name: str,
    boundary: int,
    tmp_path: Path,
) -> None:
    collector = FakeCollector(make_snapshot())

    result = main(
        [
            "--url",
            "https://example.test",
            "--output",
            str(tmp_path),
            option,
            str(boundary),
        ],
        collector_factory=lambda headed: collector,
    )

    assert result == 0
    assert collector.collect_calls == 1
    assert collector.last_limits is not None
    assert getattr(collector.last_limits, field_name) == boundary
    assert (tmp_path / "snapshot.json").exists()


def test_real_cli_collects_fixture(
    primary_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["--url", primary_url, "--output", str(tmp_path)])

    output_path = tmp_path / "snapshot.json"
    serialized = output_path.read_text(encoding="utf-8")
    SnapshotDocument.model_validate(json.loads(serialized))
    schema = json.loads(_SNAPSHOT_V1_1_SCHEMA_PATH.read_text(encoding="utf-8"))
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


def test_real_cli_identity_fixture_is_deterministic_and_safe(
    primary_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity_url = f"{primary_url}&scrollFixture=identity"
    output_directories = [tmp_path / "first", tmp_path / "second"]
    results = [
        main(["--url", identity_url, "--output", str(output_directory)])
        for output_directory in output_directories
    ]
    payloads = [
        json.loads((output_directory / "snapshot.json").read_text(encoding="utf-8"))
        for output_directory in output_directories
    ]
    schema = json.loads(_SNAPSHOT_V1_1_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    for payload in payloads:
        validator.validate(payload)
        SnapshotDocument.model_validate(payload)

    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True)
    captured = capsys.readouterr()
    assert all(result in {0, 2} for result in results)
    assert _normalize_runtime_fields(payloads[0]) == _normalize_runtime_fields(payloads[1])
    assert all(
        secret not in serialized + captured.out + captured.err
        for secret in (
            "fixture-password-do-not-return",
            "fixture-hidden-do-not-return",
            "fixture-scroll-secret-do-not-return",
        )
    )
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == [
        "snapshot.json",
        "snapshot.json",
    ]


def test_legacy_snapshot_validates_with_committed_v1_schema() -> None:
    payload = make_legacy_snapshot().model_dump(mode="json")
    schema = json.loads(_SNAPSHOT_V1_SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    assert SnapshotDocumentV1.model_validate(payload).schema_version == "1.0"


def _normalize_runtime_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _normalize_runtime_fields(item)
            for key, item in sorted(value.items())
            if key not in _RUNTIME_FIELDS
        }
    if isinstance(value, list):
        return [_normalize_runtime_fields(item) for item in value]
    return value
