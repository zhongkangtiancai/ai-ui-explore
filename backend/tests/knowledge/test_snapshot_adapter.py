"""Tests for strict, version-dispatched Snapshot loading."""

import json
import traceback
from pathlib import Path

import pytest
from backend.tests.snapshot.factories import make_legacy_snapshot, make_snapshot

from ai_ui_explorer.knowledge.snapshot_adapter import (
    InvalidSnapshotError,
    SnapshotReadError,
    UnsupportedSnapshotVersionError,
    load_snapshot,
)
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotDocumentV1


def test_load_snapshot_dispatches_exact_supported_versions(tmp_path: Path) -> None:
    current_path = tmp_path / "current.json"
    legacy_path = tmp_path / "legacy.json"
    current_path.write_text(
        make_snapshot().model_dump_json(),
        encoding="utf-8",
    )
    legacy_path.write_text(
        make_legacy_snapshot().model_dump_json(),
        encoding="utf-8",
    )

    current = load_snapshot(current_path)
    legacy = load_snapshot(legacy_path)

    assert type(current) is SnapshotDocument
    assert type(legacy) is SnapshotDocumentV1


def test_load_snapshot_does_not_repair_or_downgrade_payload(
    tmp_path: Path,
) -> None:
    payload = make_snapshot().model_dump(mode="json")
    payload["schema_version"] = "1.0"
    path = tmp_path / "mislabeled.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        InvalidSnapshotError,
        match=r"^Snapshot payload is invalid\.$",
    ):
        load_snapshot(path)


def test_load_snapshot_rejects_nonstandard_json_constants(
    tmp_path: Path,
) -> None:
    payload = make_snapshot().model_dump(mode="json")
    payload["frames"][0]["elements"][0]["bounds"]["x"] = float("nan")
    serialized = json.dumps(payload)
    assert "NaN" in serialized
    path = tmp_path / "nonstandard.json"
    path.write_text(serialized, encoding="utf-8")

    with pytest.raises(
        InvalidSnapshotError,
        match=r"^Snapshot payload is invalid\.$",
    ):
        load_snapshot(path)


@pytest.mark.parametrize(
    ("target", "replacement"),
    [
        (
            '"schema_version":"1.1"',
            (
                '"schema_version":"synthetic-secret-version",'
                '"schema_version":"1.1"'
            ),
        ),
        (
            '"title":"Example page"',
            (
                '"title":"synthetic-secret-body",'
                '"title":"Example page"'
            ),
        ),
    ],
    ids=["duplicate-schema-version", "nested-duplicate-key"],
)
def test_load_snapshot_rejects_duplicate_json_object_keys_without_leaking(
    tmp_path: Path,
    target: str,
    replacement: str,
) -> None:
    serialized = make_snapshot().model_dump_json()
    assert target in serialized
    ambiguous = serialized.replace(target, replacement, 1)
    path = tmp_path / "duplicate.json"
    path.write_text(ambiguous, encoding="utf-8")

    with pytest.raises(InvalidSnapshotError) as captured:
        load_snapshot(path)

    assert str(captured.value) == "Snapshot payload is invalid."
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    surface = _exception_surface(captured.value)
    assert "synthetic-secret" not in surface
    assert replacement not in surface


@pytest.mark.parametrize(
    ("legacy", "field_kind"),
    [
        (False, "integer"),
        (False, "boolean"),
        (True, "integer"),
        (True, "boolean"),
    ],
    ids=[
        "v1.1-string-integer",
        "v1.1-string-boolean",
        "v1.0-string-integer",
        "v1.0-string-boolean",
    ],
)
def test_load_snapshot_validates_raw_payload_against_exact_version_schema(
    tmp_path: Path,
    legacy: bool,
    field_kind: str,
) -> None:
    snapshot = make_legacy_snapshot() if legacy else make_snapshot()
    payload = snapshot.model_dump(mode="json")
    payload["source"]["title"] = "synthetic-secret-body"
    if field_kind == "integer":
        payload["page"]["viewport_width"] = "1280"
    else:
        payload["frames"][0]["elements"][0]["visible"] = "false"
    path = tmp_path / "schema-invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidSnapshotError) as captured:
        load_snapshot(path)

    assert str(captured.value) == "Snapshot payload is invalid."
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    surface = _exception_surface(captured.value)
    assert "synthetic-secret" not in surface
    assert "viewport_width" not in surface
    assert "visible" not in surface


@pytest.mark.parametrize(
    ("filename", "contents", "error_type", "summary"),
    [
        (
            "unknown.json",
            json.dumps(
                {
                    "schema_version": "synthetic-secret-version",
                    "page_body": "synthetic-secret-body",
                }
            ),
            UnsupportedSnapshotVersionError,
            "Snapshot schema version is unsupported.",
        ),
        (
            "invalid-json.json",
            '{"schema_version":"1.1","page_body":"synthetic-secret-body"',
            InvalidSnapshotError,
            "Snapshot payload is invalid.",
        ),
        (
            "invalid-payload.json",
            json.dumps(
                {
                    **make_snapshot().model_dump(mode="json"),
                    "synthetic-secret-body": "synthetic-secret-token",
                }
            ),
            InvalidSnapshotError,
            "Snapshot payload is invalid.",
        ),
    ],
)
def test_load_snapshot_errors_have_fixed_non_sensitive_exception_surfaces(
    tmp_path: Path,
    filename: str,
    contents: str,
    error_type: type[Exception],
    summary: str,
) -> None:
    path = tmp_path / filename
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(error_type) as captured:
        load_snapshot(path)

    assert str(captured.value) == summary
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    surface = _exception_surface(captured.value)
    assert "synthetic-secret" not in surface
    assert "page_body" not in surface


def test_load_snapshot_io_error_does_not_echo_sensitive_path(
    tmp_path: Path,
) -> None:
    sensitive_path = tmp_path / "synthetic-secret-snapshot.json"

    with pytest.raises(SnapshotReadError) as captured:
        load_snapshot(sensitive_path)

    assert str(captured.value) == "Snapshot file could not be read."
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "synthetic-secret" not in _exception_surface(captured.value)


def _exception_surface(error: BaseException) -> str:
    pending = [error]
    seen: set[int] = set()
    parts: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        parts.extend((str(current), repr(current)))
        parts.extend(traceback.TracebackException.from_exception(current).format())
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(parts)
