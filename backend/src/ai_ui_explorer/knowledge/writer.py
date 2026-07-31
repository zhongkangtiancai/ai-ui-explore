"""Bounded, schema-validated, atomic Knowledge Package persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ai_ui_explorer.knowledge.ids import canonical_json, stable_id
from ai_ui_explorer.knowledge.models import (
    EntityType,
    ExplorationStatus,
    Fact,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeGapReason,
    KnowledgeLocator,
    KnowledgePackage,
    KnowledgeStatistics,
    KnowledgeStatus,
    Observation,
)


class KnowledgePackageTooLargeError(ValueError):
    """Required Knowledge Package metadata cannot fit the configured JSON budget."""


class KnowledgePackageExistsError(FileExistsError):
    """The immutable Knowledge Package output already contains different bytes."""


def compact_knowledge_package(package: KnowledgePackage) -> KnowledgePackage:
    """Return a deterministic package that satisfies count and byte budgets."""

    compacted = _apply_count_budgets(package)
    if _encoded_size(compacted) <= compacted.limits.max_json_bytes:
        return compacted
    compacted = _mark_partial(compacted, "knowledge_json_size_limit")
    compacted = _fit_json_budget(compacted)
    if _encoded_size(compacted) > compacted.limits.max_json_bytes:
        raise KnowledgePackageTooLargeError(
            "knowledge package exceeds max_json_bytes after compaction"
        )
    return compacted


def write_knowledge_package(package: KnowledgePackage, output_dir: Path) -> Path:
    """Write one bounded package through a validated sibling temporary file."""

    compacted = compact_knowledge_package(package)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "knowledge-package.json"
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(_serialize(compacted))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        serialized = temporary_path.read_text(encoding="utf-8")
        payload = json.loads(serialized)
        KnowledgePackage.model_validate(payload)
        _knowledge_schema_validator().validate(payload)

        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() == temporary_path.read_bytes():
                return output_path
            raise KnowledgePackageExistsError(
                "knowledge-package.json already contains a different package"
            ) from None
        return output_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _apply_count_budgets(package: KnowledgePackage) -> KnowledgePackage:
    facts = list(package.facts)
    observations = list(package.observations)
    gaps = list(package.knowledge_gaps)
    locator_counts: Counter[str] = Counter()
    locators = []
    for locator in package.locator_candidates:
        locator_counts[locator.element_ref] += 1
        if locator_counts[locator.element_ref] <= package.limits.max_locators_per_element:
            locators.append(locator)
    stop_reasons: list[str] = []
    if len(facts) > package.limits.max_facts:
        facts = facts[: package.limits.max_facts]
        stop_reasons.append("knowledge_fact_limit")
    if len(observations) > package.limits.max_observations:
        observations = observations[: package.limits.max_observations]
        stop_reasons.append("knowledge_observation_limit")
    if len(gaps) > package.limits.max_knowledge_gaps:
        gaps = gaps[: package.limits.max_knowledge_gaps]
        stop_reasons.append("knowledge_gap_limit")
    if len(locators) != len(package.locator_candidates):
        stop_reasons.append("knowledge_locator_limit")
    if not stop_reasons:
        return _with_reference_closure(package)
    return _mark_partial(
        package,
        *stop_reasons,
        facts=facts,
        observations=observations,
        knowledge_gaps=gaps,
        locator_candidates=locators,
    )


def _fit_json_budget(package: KnowledgePackage) -> KnowledgePackage:
    result = package
    if result.observations and _encoded_size(result) > result.limits.max_json_bytes:
        observations = list(result.observations)
        result = _largest_fitting_prefix(
            result,
            observations,
            lambda retained: _with_reference_closure(
                result,
                observations=retained,
            ),
        )
    if result.locator_candidates and _encoded_size(result) > result.limits.max_json_bytes:
        locators = list(result.locator_candidates)
        result = _largest_fitting_prefix(
            result,
            locators,
            lambda retained: _with_reference_closure(
                result,
                locator_candidates=retained,
            ),
        )
    non_relationship_facts = [
        fact for fact in result.facts if fact.object_ref is None
    ]
    if non_relationship_facts and _encoded_size(result) > result.limits.max_json_bytes:
        relationship_facts = {
            fact.fact_id for fact in result.facts if fact.object_ref is not None
        }

        def retain_non_relationship_facts(retained: list[Fact]) -> KnowledgePackage:
            retained_ids = {fact.fact_id for fact in retained}
            facts = [
                fact
                for fact in result.facts
                if fact.fact_id in relationship_facts or fact.fact_id in retained_ids
            ]
            return _with_reference_closure(result, facts=facts)

        result = _largest_fitting_prefix(
            result,
            non_relationship_facts,
            retain_non_relationship_facts,
        )
    element_entities = [
        entity
        for entity in result.entities
        if entity.entity_type == EntityType.ELEMENT
    ]
    if element_entities and _encoded_size(result) > result.limits.max_json_bytes:
        non_element_ids = {
            entity.entity_id
            for entity in result.entities
            if entity.entity_type != EntityType.ELEMENT
        }

        def retain_element_entities(
            retained: list[KnowledgeEntity],
        ) -> KnowledgePackage:
            retained_ids = {entity.entity_id for entity in retained}
            entities = [
                entity
                for entity in result.entities
                if entity.entity_id in non_element_ids
                or entity.entity_id in retained_ids
            ]
            return _with_reference_closure(result, entities=entities)

        result = _largest_fitting_prefix(
            result,
            element_entities,
            retain_element_entities,
        )
    return result


def _largest_fitting_prefix[T](
    package: KnowledgePackage,
    items: Sequence[T],
    rebuild: Callable[[list[T]], KnowledgePackage],
) -> KnowledgePackage:
    low = 0
    high = len(items) - 1
    smallest = rebuild([])
    best: KnowledgePackage | None = (
        smallest
        if _encoded_size(smallest) <= package.limits.max_json_bytes
        else None
    )
    while low <= high:
        midpoint = (low + high) // 2
        candidate = rebuild(list(items[: midpoint + 1]))
        if _encoded_size(candidate) <= package.limits.max_json_bytes:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best or smallest


def _mark_partial(
    package: KnowledgePackage,
    *new_stop_reasons: str,
    **updates: object,
) -> KnowledgePackage:
    stop_reasons = sorted({*package.stop_reasons, *new_stop_reasons})
    gaps = list(
        cast(
            Sequence[KnowledgeGap],
            updates.get("knowledge_gaps", package.knowledge_gaps),
        )
    )
    if not any(
        gap.reason_code == KnowledgeGapReason.COLLECTION_TRUNCATED for gap in gaps
    ):
        gaps = _append_truncation_gap(package, gaps)
    exploration_run = package.exploration_run
    if exploration_run.exploration_status == ExplorationStatus.COMPLETED:
        exploration_run = exploration_run.model_copy(
            update={"exploration_status": ExplorationStatus.PARTIAL}
        )
    updates.update(
        {
            "status": KnowledgeStatus.PARTIAL,
            "knowledge_gaps": gaps,
            "stop_reasons": stop_reasons,
            "exploration_run": exploration_run,
        }
    )
    return _with_reference_closure(package, **updates)


def _append_truncation_gap(
    package: KnowledgePackage,
    gaps: list[KnowledgeGap],
) -> list[KnowledgeGap]:
    gap = KnowledgeGap(
        gap_id=stable_id(
            "gap",
            package.exploration_run.exploration_run_id,
            "exploration.collection",
            KnowledgeGapReason.COLLECTION_TRUNCATED.value,
        ),
        subject_ref=package.exploration_run.exploration_run_id,
        aspect="exploration.collection",
        reason_code=KnowledgeGapReason.COLLECTION_TRUNCATED,
        reason="The Knowledge Package was compacted to satisfy configured budgets.",
        evidence_refs=[],
        verification="Increase budgets or rebuild from a smaller source snapshot.",
    )
    if len(gaps) < package.limits.max_knowledge_gaps:
        return [*gaps, gap]
    if not gaps:
        return [gap]
    return [*gaps[:-1], gap]


def _with_reference_closure(
    package: KnowledgePackage,
    **updates: object,
) -> KnowledgePackage:
    entities = list(
        cast(
            Sequence[KnowledgeEntity],
            updates.get("entities", package.entities),
        )
    )
    locators = list(
        cast(
            Sequence[KnowledgeLocator],
            updates.get("locator_candidates", package.locator_candidates),
        )
    )
    facts = list(
        cast(Sequence[Fact], updates.get("facts", package.facts))
    )
    observations = list(
        cast(
            Sequence[Observation],
            updates.get("observations", package.observations),
        )
    )
    gaps = list(
        cast(
            Sequence[KnowledgeGap],
            updates.get("knowledge_gaps", package.knowledge_gaps),
        )
    )
    subject_ids = {
        package.application.application_id,
        package.exploration_run.exploration_run_id,
        *{entity.entity_id for entity in entities},
    }
    facts = [
        fact
        for fact in facts
        if fact.subject_ref in subject_ids
        and (fact.object_ref is None or fact.object_ref in subject_ids)
    ]
    located_in = {
        fact.subject_ref: fact.object_ref
        for fact in facts
        if fact.object_ref is not None
        and fact.predicate.value == "element.located_in"
    }
    locators = [
        locator
        for locator in locators
        if locator.element_ref in subject_ids
        and locator.frame_ref in subject_ids
        and located_in.get(locator.element_ref) == locator.frame_ref
    ]
    subject_ids.update(locator.locator_id for locator in locators)
    facts = [
        fact
        for fact in facts
        if fact.subject_ref in subject_ids
        and (fact.object_ref is None or fact.object_ref in subject_ids)
    ]
    observations = [
        observation
        for observation in observations
        if observation.subject_ref in subject_ids
    ]
    gaps = [gap for gap in gaps if gap.subject_ref in subject_ids]
    referenced_evidence = {
        evidence_ref
        for entity in entities
        for evidence_ref in entity.source_refs
    }
    referenced_evidence.update(
        evidence_ref
        for locator in locators
        for evidence_ref in locator.evidence_refs
    )
    referenced_evidence.update(
        evidence_ref for fact in facts for evidence_ref in fact.evidence_refs
    )
    referenced_evidence.update(
        evidence_ref
        for observation in observations
        for evidence_ref in observation.evidence_refs
    )
    referenced_evidence.update(
        evidence_ref
        for gap in gaps
        for evidence_ref in gap.evidence_refs
    )
    evidence = [
        item for item in package.evidence if item.evidence_id in referenced_evidence
    ]
    statistics = KnowledgeStatistics(
        entity_count=len(entities),
        locator_candidate_count=len(locators),
        evidence_count=len(evidence),
        fact_count=len(facts),
        observation_count=len(observations),
        inference_count=len(package.inferences),
        knowledge_gap_count=len(gaps),
    )
    values = package.model_dump(mode="python")
    values.update(updates)
    values.update(
        {
            "entities": entities,
            "locator_candidates": locators,
            "evidence": evidence,
            "facts": facts,
            "observations": observations,
            "knowledge_gaps": gaps,
            "statistics": statistics,
        }
    )
    return KnowledgePackage.model_validate(values)


def _encoded_size(package: KnowledgePackage) -> int:
    return len(_serialize(package).encode("utf-8"))


def _serialize(package: KnowledgePackage) -> str:
    return canonical_json(package.model_dump(mode="json"))


@lru_cache(maxsize=1)
def _knowledge_schema_validator() -> Draft202012Validator:
    serialized = (
        resources.files("ai_ui_explorer.knowledge")
        .joinpath("schema", "knowledge-package-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    payload = json.loads(serialized)
    if not isinstance(payload, dict):
        raise KnowledgePackageTooLargeError("knowledge schema is invalid")
    try:
        Draft202012Validator.check_schema(payload)
    except SchemaError as error:
        raise KnowledgePackageTooLargeError("knowledge schema is invalid") from error
    return Draft202012Validator(payload)
