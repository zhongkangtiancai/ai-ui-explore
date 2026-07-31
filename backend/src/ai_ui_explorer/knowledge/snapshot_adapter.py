"""Strict, version-dispatched loading for persisted Snapshot documents."""

import json
from enum import Enum, auto
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import NoReturn, cast

import jsonschema.exceptions as jsonschema_exceptions
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_ui_explorer.snapshot.models import (
    AnySnapshotDocument,
    SnapshotDocument,
    SnapshotDocumentV1,
)


class SnapshotLoadError(ValueError):
    """Base error for safe Snapshot loading failures."""


class SnapshotReadError(SnapshotLoadError):
    """The Snapshot file could not be read as UTF-8 text."""


class InvalidSnapshotError(SnapshotLoadError):
    """The Snapshot is not valid JSON or violates its exact model."""


class UnsupportedSnapshotVersionError(SnapshotLoadError):
    """The Snapshot declares a schema version this adapter does not support."""


class _LoadFailure(Enum):
    READ = auto()
    INVALID = auto()
    UNSUPPORTED_VERSION = auto()


_SNAPSHOT_SCHEMA_FILES = {
    "1.0": "snapshot-v1.schema.json",
    "1.1": "snapshot-v1.1.schema.json",
}


def load_snapshot(path: Path) -> AnySnapshotDocument:
    """Load a valid 1.0 or 1.1 Snapshot without repair or version guessing."""

    snapshot, failure = _try_load_snapshot(path)
    del path
    if failure is _LoadFailure.READ:
        raise SnapshotReadError("Snapshot file could not be read.")
    if failure is _LoadFailure.INVALID:
        raise InvalidSnapshotError("Snapshot payload is invalid.")
    if failure is _LoadFailure.UNSUPPORTED_VERSION:
        raise UnsupportedSnapshotVersionError(
            "Snapshot schema version is unsupported."
        )
    assert snapshot is not None
    return snapshot


def _try_load_snapshot(
    path: Path,
) -> tuple[AnySnapshotDocument | None, _LoadFailure | None]:
    try:
        serialized = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, _LoadFailure.READ

    try:
        decoded: object = json.loads(
            serialized,
            object_pairs_hook=_object_with_unique_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (RecursionError, ValueError):
        return None, _LoadFailure.INVALID
    if not isinstance(decoded, dict):
        return None, _LoadFailure.INVALID
    payload = cast(dict[str, object], decoded)

    raw_version = payload.get("schema_version")
    version: str
    model: type[SnapshotDocumentV1] | type[SnapshotDocument]
    if raw_version == "1.0":
        version = "1.0"
        model = SnapshotDocumentV1
    elif raw_version == "1.1":
        version = "1.1"
        model = SnapshotDocument
    else:
        return None, _LoadFailure.UNSUPPORTED_VERSION

    if not _payload_matches_committed_schema(payload, version):
        return None, _LoadFailure.INVALID

    try:
        return model.model_validate(payload), None
    except ValidationError:
        return None, _LoadFailure.INVALID


def _reject_nonstandard_json_constant(value: str) -> NoReturn:
    del value
    raise ValueError("non-standard JSON numeric constant")


def _object_with_unique_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _payload_matches_committed_schema(
    payload: dict[str, object],
    version: str,
) -> bool:
    validator = _load_snapshot_schema_validator(version)
    if validator is None:
        return False
    try:
        validator.validate(payload)
    except jsonschema_exceptions.ValidationError:
        return False
    return True


@lru_cache(maxsize=2)
def _load_snapshot_schema_validator(
    version: str,
) -> Draft202012Validator | None:
    filename = _SNAPSHOT_SCHEMA_FILES.get(version)
    if filename is None:
        return None
    try:
        serialized = (
            resources.files("ai_ui_explorer.snapshot")
            .joinpath("schema", filename)
            .read_text(encoding="utf-8")
        )
        decoded: object = json.loads(serialized)
        if not isinstance(decoded, dict):
            return None
        schema = cast(dict[str, object], decoded)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except (
        OSError,
        RecursionError,
        jsonschema_exceptions.SchemaError,
        UnicodeError,
        ValueError,
    ):
        return None
