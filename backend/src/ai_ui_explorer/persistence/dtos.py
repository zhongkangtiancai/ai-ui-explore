"""Validation for the strict JSON boundary of PostgreSQL persistence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Set

from pydantic import Field, model_validator

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import PageEvidence
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport

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


class PersistedTaskPageEvidence(DeepFrozenModel):
    """One page detail paired with its process-safe public page identifier."""

    page_id: str = Field(pattern=r"^page-[0-9]{1,20}$")
    page: PageEvidence


class TaskEvidencePersistencePayload(DeepFrozenModel):
    """Complete redacted task evidence required for restart-safe knowledge exports."""

    export: ExplorationEvidenceExport
    pages: list[PersistedTaskPageEvidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_matching_page_indexes(self) -> TaskEvidencePersistencePayload:
        export_pages = {page.page_id: page.page_key for page in self.export.pages}
        detail_pages = {page.page_id: page.page.page_key for page in self.pages}
        if export_pages != detail_pages:
            raise ValueError("persisted page IDs must match evidence export")
        return self


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
