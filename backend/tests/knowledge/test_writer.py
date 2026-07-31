"""Tests for bounded, atomic Knowledge Package persistence."""

import json
import os
from pathlib import Path

import pytest

import ai_ui_explorer.knowledge.writer as writer_module
from ai_ui_explorer.knowledge.builder import KnowledgePackageBuilder
from ai_ui_explorer.knowledge.models import (
    EntityType,
    KnowledgeLimits,
    KnowledgePackage,
)
from ai_ui_explorer.knowledge.predicates import Predicate
from ai_ui_explorer.knowledge.writer import (
    KnowledgePackageExistsError,
    compact_knowledge_package,
    write_knowledge_package,
)
from tests.knowledge.factories import make_manifest, make_package
from tests.snapshot.factories import make_element, make_frame, make_snapshot


def test_writer_creates_schema_valid_atomic_file(tmp_path: Path) -> None:
    output = write_knowledge_package(make_package(), tmp_path)

    assert output == tmp_path / "knowledge-package.json"
    assert not list(tmp_path.glob("*.tmp"))
    KnowledgePackage.model_validate_json(output.read_text(encoding="utf-8"))


def test_writer_is_idempotent_for_identical_package(tmp_path: Path) -> None:
    package = make_package()

    first = write_knowledge_package(package, tmp_path)
    second = write_knowledge_package(package, tmp_path)

    assert first == second
    assert first.read_bytes() == second.read_bytes()
    assert not list(tmp_path.glob("*.tmp"))


def test_writer_refuses_to_replace_different_package(tmp_path: Path) -> None:
    first_package = make_package()
    existing = write_knowledge_package(first_package, tmp_path)
    original = existing.read_bytes()
    second_package = make_package(package_id="kp-different")

    with pytest.raises(KnowledgePackageExistsError):
        write_knowledge_package(second_package, tmp_path)

    assert existing.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_compaction_applies_fact_budget_and_keeps_reference_closure() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_snapshot(),
        limits=KnowledgeLimits(max_facts=1),
    )

    compacted = compact_knowledge_package(package)

    assert compacted.status == "partial"
    assert compacted.statistics.fact_count == 1
    assert len(compacted.facts) == 1
    assert "knowledge_fact_limit" in compacted.stop_reasons
    evidence_ids = {item.evidence_id for item in compacted.evidence}
    referenced_evidence = {
        evidence_ref
        for collection in (
            compacted.entities,
            compacted.locator_candidates,
            compacted.facts,
            compacted.observations,
            compacted.knowledge_gaps,
        )
        for item in collection
        for evidence_ref in getattr(item, "source_refs", getattr(item, "evidence_refs", []))
    }
    assert referenced_evidence == evidence_ids


def test_json_budget_returns_valid_partial_package_with_relationships() -> None:
    elements = [
        make_element(
            element_id=f"element-{index}",
            traversal_index=index,
            accessible_name=f"Element {index} " + ("x" * 120),
            text="y" * 120,
        )
        for index in range(250)
    ]
    snapshot = make_snapshot(
        frames=[make_frame(elements=elements)],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": len(elements),
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "locator_candidate_count": 0,
            "duration_ms": 1,
        },
    )
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=snapshot,
        limits=KnowledgeLimits(max_json_bytes=65_536),
    )
    assert len(writer_module._serialize(package).encode("utf-8")) > 65_536

    compacted = compact_knowledge_package(package)

    assert compacted.status == "partial"
    assert "knowledge_json_size_limit" in compacted.stop_reasons
    assert len(writer_module._serialize(compacted).encode("utf-8")) <= 65_536
    assert any(
        gap.reason_code == "collection_truncated"
        for gap in compacted.knowledge_gaps
    )
    element_ids = {
        entity.entity_id
        for entity in compacted.entities
        if entity.entity_type == EntityType.ELEMENT
    }
    located_elements = {
        fact.subject_ref
        for fact in compacted.facts
        if fact.predicate == Predicate.ELEMENT_LOCATED_IN
    }
    assert element_ids <= located_elements


def test_writer_does_not_overwrite_file_created_during_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concurrent_bytes = b'{"owner":"concurrent"}'
    real_link = os.link

    def create_competing_file_then_link(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        Path(destination).write_bytes(concurrent_bytes)
        real_link(source, destination)

    monkeypatch.setattr(
        writer_module.os,
        "link",
        create_competing_file_then_link,
    )

    with pytest.raises(KnowledgePackageExistsError):
        write_knowledge_package(make_package(), tmp_path)

    assert (tmp_path / "knowledge-package.json").read_bytes() == concurrent_bytes
    assert not list(tmp_path.glob("*.tmp"))


def test_writer_cleans_temporary_file_when_atomic_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(writer_module.os, "link", fail_link)

    with pytest.raises(OSError, match="synthetic publish failure"):
        write_knowledge_package(make_package(), tmp_path)

    assert not (tmp_path / "knowledge-package.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_writer_output_validates_committed_schema(tmp_path: Path) -> None:
    output = write_knowledge_package(make_package(), tmp_path)

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0"
    assert payload["package_id"] == "kp-example"
