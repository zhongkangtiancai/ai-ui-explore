"""Bounded context envelope construction for LLM calls."""

import hashlib
import json
from collections import OrderedDict
from typing import Literal

from pydantic import Field

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.knowledge.models import Evidence, KnowledgePackage
from ai_ui_explorer.llm.token_budget import estimate_tokens


class ContextRequest(DeepFrozenModel):
    package: KnowledgePackage
    task: str = Field(min_length=1)
    identity_alias: str | None = None


class ContextRecord(DeepFrozenModel):
    record_type: Literal["entity", "locator", "fact", "observation", "gap"]
    record_id: str = Field(min_length=1)
    payload: dict[str, object]
    evidence_refs: list[str]


class ContextEnvelope(DeepFrozenModel):
    application_id: str
    environment: str
    identity_alias: str | None
    task: str
    records: list[ContextRecord]
    evidence: list[Evidence]
    estimated_tokens: int
    truncated: bool
    stop_reasons: list[str]
    cache_key: str
    cache_hit: bool


class ContextManager:
    def __init__(
        self,
        *,
        max_estimated_tokens: int = 8_000,
        cache_size: int = 32,
    ) -> None:
        if max_estimated_tokens < 1:
            raise ValueError("max_estimated_tokens must be positive")
        if cache_size < 0:
            raise ValueError("cache_size must not be negative")
        self._max_estimated_tokens = max_estimated_tokens
        self._cache_size = cache_size
        self._cache: OrderedDict[str, ContextEnvelope] = OrderedDict()

    def build(self, request: ContextRequest) -> ContextEnvelope:
        cache_key = _cache_key(request)
        if cache_key in self._cache:
            cached = self._cache.pop(cache_key)
            self._cache[cache_key] = cached
            return cached.model_copy(update={"cache_hit": True})

        records, truncated = self._select_records(request.package)
        evidence = _evidence_closure(request.package, records)
        estimated_tokens = estimate_tokens(
            {
                "task": request.task,
                "records": [record.model_dump(mode="json") for record in records],
                "evidence": [item.model_dump(mode="json") for item in evidence],
            }
        )
        envelope = ContextEnvelope(
            application_id=request.package.application.application_id,
            environment=request.package.application.environment,
            identity_alias=request.identity_alias,
            task=request.task,
            records=records,
            evidence=evidence,
            estimated_tokens=estimated_tokens,
            truncated=truncated,
            stop_reasons=["context_token_budget"] if truncated else [],
            cache_key=cache_key,
            cache_hit=False,
        )
        self._remember(cache_key, envelope)
        return envelope

    def _select_records(
        self,
        package: KnowledgePackage,
    ) -> tuple[list[ContextRecord], bool]:
        selected: list[ContextRecord] = []
        total = 0
        truncated = False
        for record in _iter_records(package):
            cost = estimate_tokens(record.model_dump(mode="json"))
            if total + cost > self._max_estimated_tokens:
                truncated = True
                break
            selected.append(record)
            total += cost
        return selected, truncated

    def _remember(self, key: str, envelope: ContextEnvelope) -> None:
        if self._cache_size == 0:
            return
        self._cache[key] = envelope
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _iter_records(package: KnowledgePackage) -> list[ContextRecord]:
    records: list[ContextRecord] = []
    records.extend(
        ContextRecord(
            record_type="entity",
            record_id=item.entity_id,
            payload=item.model_dump(mode="json"),
            evidence_refs=list(item.source_refs),
        )
        for item in package.entities
    )
    records.extend(
        ContextRecord(
            record_type="locator",
            record_id=item.locator_id,
            payload=item.model_dump(mode="json"),
            evidence_refs=list(item.evidence_refs),
        )
        for item in package.locator_candidates
    )
    records.extend(
        ContextRecord(
            record_type="fact",
            record_id=item.fact_id,
            payload=item.model_dump(mode="json"),
            evidence_refs=list(item.evidence_refs),
        )
        for item in package.facts
    )
    records.extend(
        ContextRecord(
            record_type="observation",
            record_id=item.observation_id,
            payload=item.model_dump(mode="json"),
            evidence_refs=list(item.evidence_refs),
        )
        for item in package.observations
    )
    records.extend(
        ContextRecord(
            record_type="gap",
            record_id=item.gap_id,
            payload=item.model_dump(mode="json"),
            evidence_refs=list(item.evidence_refs),
        )
        for item in package.knowledge_gaps
    )
    return records


def _evidence_closure(
    package: KnowledgePackage,
    records: list[ContextRecord],
) -> list[Evidence]:
    referenced = {
        evidence_ref for record in records for evidence_ref in record.evidence_refs
    }
    return [item for item in package.evidence if item.evidence_id in referenced]


def _cache_key(request: ContextRequest) -> str:
    package_digest = hashlib.sha256(
        request.package.model_dump_json().encode("utf-8")
    ).hexdigest()
    values = {
        "application_id": request.package.application.application_id,
        "environment": request.package.application.environment,
        "identity_alias": request.identity_alias,
        "package_digest": package_digest,
        "task": request.task,
    }
    return hashlib.sha256(
        json.dumps(
            values,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
