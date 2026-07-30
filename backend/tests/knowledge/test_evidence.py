"""Tests for deterministic, redacted, bounded Snapshot evidence."""

import traceback
from hashlib import sha256
from uuid import UUID

import pytest
from backend.tests.snapshot.factories import make_frame, make_snapshot

from ai_ui_explorer.knowledge.evidence import (
    EvidenceBuilder,
    EvidenceConfigurationError,
    EvidenceRequestError,
)
from ai_ui_explorer.knowledge.ids import canonical_json, stable_id
from ai_ui_explorer.snapshot.redaction import Redactor


def test_evidence_is_traceable_redacted_and_bounded() -> None:
    snapshot = make_snapshot(
        frames=[
            make_frame(
                text_summary="前缀🙂 token=synthetic-secret 后缀",
            )
        ]
    )
    builder = EvidenceBuilder(
        snapshot=snapshot,
        redactor=Redactor(),
        excerpt_limit=20,
    )

    evidence = builder.at("/frames/0/text_summary", "frame.text_summary")
    snapshot_payload = snapshot.model_dump(mode="json")
    expected_digest = sha256(
        canonical_json(snapshot_payload).encode("utf-8")
    ).hexdigest()
    expected_excerpt = Redactor().redact_text(
        "前缀🙂 token=synthetic-secret 后缀"
    ).value[:20]

    assert evidence.snapshot_id == snapshot.snapshot_id
    assert isinstance(evidence.snapshot_id, UUID)
    assert evidence.model_dump(mode="json")["snapshot_id"] == str(
        snapshot.snapshot_id
    )
    assert evidence.snapshot_schema_version == "1.1"
    assert evidence.snapshot_sha256 == expected_digest
    assert evidence.json_pointer == "/frames/0/text_summary"
    assert evidence.evidence_type == "frame.text_summary"
    assert evidence.excerpt == expected_excerpt
    assert "synthetic-secret" not in evidence.excerpt
    assert len(evidence.excerpt) <= 20
    assert evidence.evidence_id == stable_id(
        "evidence",
        expected_digest,
        "/frames/0/text_summary",
        "frame.text_summary",
    )


def test_evidence_uses_url_redaction_only_for_url_evidence_types() -> None:
    snapshot = make_snapshot(
        source={
            "requested_url": "https://example.test/",
            "final_url": (
                "https://user:synthetic-secret@example.test/path"
                "?token=synthetic-secret"
            ),
            "title": "Example page",
        }
    )
    builder = EvidenceBuilder(
        snapshot=snapshot,
        redactor=Redactor(),
        excerpt_limit=500,
    )

    evidence = builder.at("/source/final_url", "page.final_url")

    assert evidence.excerpt == (
        "https://example.test/path?token=%5BREDACTED%3ATOKEN%5D"
    )
    assert "synthetic-secret" not in evidence.excerpt


def test_evidence_does_not_trust_an_arbitrary_url_suffix() -> None:
    snapshot = make_snapshot(
        source={
            "requested_url": "https://example.test/",
            "final_url": "https://example.test/",
            "title": "token=synthetic-secret",
        }
    )
    builder = EvidenceBuilder(
        snapshot=snapshot,
        redactor=Redactor(),
        excerpt_limit=500,
    )

    evidence = builder.at("/source/title", "page.not_url")

    assert evidence.excerpt == "token=[REDACTED:TOKEN]"
    assert "synthetic-secret" not in evidence.excerpt


def test_evidence_canonicalizes_non_string_before_text_redaction() -> None:
    snapshot = make_snapshot(
        source={
            "requested_url": "https://example.test/",
            "final_url": "https://example.test/",
            "title": "Example page",
        }
    )
    payload = snapshot.model_dump(mode="json")
    payload["source"]["title"] = "token=synthetic-secret"
    snapshot = type(snapshot).model_validate(payload)
    builder = EvidenceBuilder(
        snapshot=snapshot,
        redactor=Redactor(),
        excerpt_limit=500,
    )

    evidence = builder.at("/source", "page.source")

    assert evidence.excerpt == (
        '{"final_url":"https://example.test/",'
        '"requested_url":"https://example.test/",'
        '"title":"token=[REDACTED:TOKEN]}'
    )
    assert "synthetic-secret" not in evidence.excerpt


def test_evidence_unicode_truncation_counts_python_characters() -> None:
    snapshot = make_snapshot(frames=[make_frame(text_summary="甲🙂乙")])
    builder = EvidenceBuilder(
        snapshot=snapshot,
        redactor=Redactor(),
        excerpt_limit=2,
    )

    evidence = builder.at("/frames/0/text_summary", "frame.text_summary")

    assert evidence.excerpt == "甲🙂"
    assert len(evidence.excerpt) == 2


def test_evidence_cache_reuses_same_instance_by_pointer_and_type() -> None:
    builder = EvidenceBuilder(
        snapshot=make_snapshot(),
        redactor=Redactor(),
        excerpt_limit=500,
    )

    first = builder.at("/source/title", "page.title")
    repeated = builder.at("/source/title", "page.title")
    different_type = builder.at("/source/title", "page.label")

    assert repeated is first
    assert different_type is not first
    assert different_type.evidence_id != first.evidence_id


@pytest.mark.parametrize("excerpt_limit", [0, 10_001, True, "500"])
def test_evidence_rejects_excerpt_limits_outside_knowledge_limits(
    excerpt_limit: object,
) -> None:
    with pytest.raises(
        EvidenceConfigurationError,
        match=r"^Evidence excerpt limit is invalid\.$",
    ) as captured:
        EvidenceBuilder(
            snapshot=make_snapshot(),
            redactor=Redactor(),
            excerpt_limit=excerpt_limit,  # type: ignore[arg-type]
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    ("pointer", "evidence_type"),
    [
        ("/source/title", ""),
        ("/source/title", "Frame.Title"),
        ("/source/title", "frame.token=synthetic-secret"),
        ("/source/title", "a" * 129),
        ("/token=synthetic-secret", "page.title"),
        ("/source/title\nsynthetic-secret", "page.title"),
    ],
)
def test_evidence_rejects_unsafe_pointer_or_type_without_echoing_input(
    pointer: str,
    evidence_type: str,
) -> None:
    builder = EvidenceBuilder(
        snapshot=make_snapshot(),
        redactor=Redactor(),
        excerpt_limit=500,
    )

    with pytest.raises(
        EvidenceRequestError,
        match=r"^Evidence request is invalid\.$",
    ) as captured:
        builder.at(pointer, evidence_type)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    surface = _exception_surface(captured.value)
    assert pointer not in surface
    if evidence_type:
        assert evidence_type not in surface
    assert "synthetic-secret" not in surface


def _exception_surface(error: BaseException) -> str:
    parts = [str(error), repr(error)]
    parts.extend(traceback.TracebackException.from_exception(error).format())
    return "\n".join(parts)
