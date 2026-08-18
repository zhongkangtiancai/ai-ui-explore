from datetime import UTC, datetime

import pytest

from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityRunState,
    PermissionComparisonResult,
)
from ai_ui_explorer.permission_comparison.service import PermissionComparisonView
from ai_ui_explorer.persistence.models import PermissionComparisonRecord
from ai_ui_explorer.persistence.repositories import (
    PersistenceProjectionError,
    comparison_record_from_view,
    comparison_view_from_record,
)


def test_comparison_projection_round_trips_terminal_result() -> None:
    view = _completed_view()
    timestamp = datetime(2026, 8, 18, tzinfo=UTC)

    record = comparison_record_from_view(
        view,
        created_at=timestamp,
        updated_at=timestamp,
    )

    assert record.comparison_id == "comparison-1"
    assert comparison_view_from_record(record) == view


def test_comparison_projection_rejects_terminal_record_without_result() -> None:
    timestamp = datetime(2026, 8, 18, tzinfo=UTC)
    record = PermissionComparisonRecord(
        comparison_id="comparison-1",
        state="failed",
        created_at=timestamp,
        updated_at=timestamp,
        identities_json={"identity-1": "failed", "identity-2": "failed"},
        result_json=None,
        schema_version="1.0",
    )

    with pytest.raises(PersistenceProjectionError, match="Persistence projection unavailable"):
        comparison_view_from_record(record)


def _completed_view() -> PermissionComparisonView:
    return PermissionComparisonView(
        comparison_id="comparison-1",
        state="completed",
        identities={"identity-1": "completed", "identity-2": "completed"},
        result=PermissionComparisonResult(
            comparison_id="comparison-1",
            status="completed",
            identities=[
                IdentityEvidenceBundle(identity_id="identity-1", state=IdentityRunState.COMPLETED),
                IdentityEvidenceBundle(identity_id="identity-2", state=IdentityRunState.COMPLETED),
            ],
        ),
    )
