"""Deterministic, redacted, bounded evidence from validated Snapshots."""

import re
from hashlib import sha256

from ai_ui_explorer.knowledge.ids import (
    JsonPointerError,
    canonical_json,
    resolve_json_pointer,
    stable_id,
)
from ai_ui_explorer.knowledge.models import Evidence
from ai_ui_explorer.snapshot.models import AnySnapshotDocument
from ai_ui_explorer.snapshot.redaction import Redactor

_SAFE_EVIDENCE_TYPE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_URL_EVIDENCE_TYPES = frozenset(
    {
        "frame.url",
        "page.final_url",
        "page.requested_url",
    }
)
_MIN_EVIDENCE_EXCERPT_CHARS = 1
_MAX_EVIDENCE_EXCERPT_CHARS = 10_000


class EvidenceError(ValueError):
    """Base error for safe EvidenceBuilder failures."""


class EvidenceConfigurationError(EvidenceError):
    """EvidenceBuilder configuration is outside the knowledge limits."""


class EvidenceRequestError(EvidenceError):
    """An Evidence request has an unsafe type or unresolved Pointer."""


class EvidenceBuilder:
    """Create and cache traceable evidence for one validated Snapshot."""

    def __init__(
        self,
        *,
        snapshot: AnySnapshotDocument,
        redactor: Redactor,
        excerpt_limit: int,
    ) -> None:
        if (
            not isinstance(excerpt_limit, int)
            or isinstance(excerpt_limit, bool)
            or not (
                _MIN_EVIDENCE_EXCERPT_CHARS
                <= excerpt_limit
                <= _MAX_EVIDENCE_EXCERPT_CHARS
            )
        ):
            raise EvidenceConfigurationError(
                "Evidence excerpt limit is invalid."
            )

        document = snapshot.model_dump(mode="json")
        serialized = canonical_json(document)
        self._snapshot_id = snapshot.snapshot_id
        self._snapshot_schema_version = snapshot.schema_version
        self._snapshot_sha256 = sha256(
            serialized.encode("utf-8")
        ).hexdigest()
        self._document = document
        self._redactor = redactor
        self._excerpt_limit = excerpt_limit
        self._cache: dict[tuple[str, str], Evidence] = {}

    def at(self, pointer: str, evidence_type: str) -> Evidence:
        """Return cached evidence for one safe, resolvable source location."""

        if (
            not isinstance(pointer, str)
            or not isinstance(evidence_type, str)
            or _SAFE_EVIDENCE_TYPE.fullmatch(evidence_type) is None
        ):
            del pointer, evidence_type
            raise EvidenceRequestError("Evidence request is invalid.")

        cache_key = (pointer, evidence_type)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        resolution_failed = False
        resolved: object = None
        try:
            resolved = resolve_json_pointer(self._document, pointer)
        except JsonPointerError:
            resolution_failed = True
        if resolution_failed:
            del pointer, evidence_type, cache_key, resolved
            raise EvidenceRequestError("Evidence request is invalid.")

        normalized = (
            resolved if isinstance(resolved, str) else canonical_json(resolved)
        )
        if evidence_type in _URL_EVIDENCE_TYPES:
            redacted = self._redactor.redact_url(normalized).value
        else:
            redacted = self._redactor.redact_text(normalized).value
        evidence = Evidence(
            evidence_id=stable_id(
                "evidence",
                self._snapshot_sha256,
                pointer,
                evidence_type,
            ),
            snapshot_id=self._snapshot_id,
            snapshot_schema_version=self._snapshot_schema_version,
            snapshot_sha256=self._snapshot_sha256,
            json_pointer=pointer,
            evidence_type=evidence_type,
            excerpt=redacted[: self._excerpt_limit],
        )
        self._cache[cache_key] = evidence
        return evidence
