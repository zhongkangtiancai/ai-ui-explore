"""Validation for the strict JSON boundary of PostgreSQL persistence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Set

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_SENSITIVE_KEY_PARTS = frozenset(
    {
        "browser",
        "cookie",
        "dom",
        "html",
        "input",
        "network",
        "password",
        "screenshot",
        "snapshot",
        "storage",
        "token",
    }
)
_MAX_JSON_BYTES = 10 * 1024 * 1024


class PersistencePayloadError(RuntimeError):
    """A JSON projection cannot safely cross the persistence boundary."""


def validate_safe_json_payload(
    payload: Mapping[str, object],
    *,
    allowed_schema_versions: Set[str],
) -> dict[str, JsonValue]:
    """Return a detached JSON copy after version and sensitive-key validation."""
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ValueError("payload exceeds byte budget")
        copied = json.loads(serialized)
        if not isinstance(copied, dict):
            raise ValueError("payload must be an object")
        schema_version = copied.get("schema_version")
        if not isinstance(schema_version, str) or schema_version not in allowed_schema_versions:
            raise ValueError("schema version is not allowed")
        _reject_sensitive_keys(copied)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistencePayloadError("Persistence payload rejected") from error
    return copied


def _reject_sensitive_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if not isinstance(key, str) or _is_sensitive_key(key):
                raise ValueError("sensitive key")
            _reject_sensitive_keys(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _reject_sensitive_keys(nested_value)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
