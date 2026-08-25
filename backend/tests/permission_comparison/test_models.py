"""Tests for the strict Sprint 6 permission comparison model contract."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_ui_explorer.permission_comparison.models import (
    DifferenceKind,
    EvidenceReference,
    IdentityProfile,
    ObservationState,
    PermissionComparisonExport,
    VisibilityDifference,
)


def _evidence_reference() -> EvidenceReference:
    return EvidenceReference(
        evidence_id="evidence-1",
        snapshot_id="snapshot-1",
        snapshot_schema_version="1.1",
        snapshot_sha256="a" * 64,
        json_pointer="/frames/0/elements/0",
        excerpt="safe button evidence",
    )


def test_identity_profile_rejects_sensitive_aliases() -> None:
    with pytest.raises(ValidationError):
        IdentityProfile(
            identity_id="identity-1",
            label="管理员 token",
            authentication_plan=None,
        )


def test_difference_becomes_inconclusive_when_one_identity_is_partial() -> None:
    difference = VisibilityDifference(
        difference_id="difference-1",
        kind=DifferenceKind.OBSERVED_IN_ONLY_ONE_IDENTITY,
        subject_key="page:https://app.example.test/admin",
        identity_states={
            "identity-1": ObservationState.OBSERVED,
            "identity-2": ObservationState.COLLECTION_INCOMPLETE,
        },
        evidence_refs=[_evidence_reference()],
        reason_codes=["collection_truncated"],
    )

    assert difference.reliability == "inconclusive"


def test_committed_permission_comparison_schema_matches_model() -> None:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "ai_ui_explorer"
        / "permission_comparison"
        / "schema"
        / "permission-comparison-v1.schema.json"
    )

    assert json.loads(schema_path.read_text(encoding="utf-8")) == (
        PermissionComparisonExport.to_schema()
    )
