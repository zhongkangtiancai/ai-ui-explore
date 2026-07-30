"""Strict, version-dispatched loading for persisted Snapshot documents."""

import json
from enum import Enum, auto
from pathlib import Path
from typing import NoReturn, cast

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
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (RecursionError, ValueError):
        return None, _LoadFailure.INVALID
    if not isinstance(decoded, dict):
        return None, _LoadFailure.INVALID
    payload = cast(dict[str, object], decoded)

    version = payload.get("schema_version")
    model: type[SnapshotDocumentV1] | type[SnapshotDocument]
    if version == "1.0":
        model = SnapshotDocumentV1
    elif version == "1.1":
        model = SnapshotDocument
    else:
        return None, _LoadFailure.UNSUPPORTED_VERSION

    try:
        return model.model_validate(payload), None
    except ValidationError:
        return None, _LoadFailure.INVALID


def _reject_nonstandard_json_constant(value: str) -> NoReturn:
    del value
    raise ValueError("non-standard JSON numeric constant")
