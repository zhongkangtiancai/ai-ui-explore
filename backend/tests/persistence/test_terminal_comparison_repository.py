from datetime import UTC, datetime

import pytest

from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityRunState,
    PermissionComparisonResult,
)
from ai_ui_explorer.permission_comparison.service import PermissionComparisonView
from ai_ui_explorer.persistence.models import (
    ExplorationKnowledgeSourceRecord,
    PermissionComparisonRecord,
)
from ai_ui_explorer.persistence.repositories import (
    PersistenceProjectionError,
    SafeTaskRepository,
)


def test_repository_persists_terminal_comparison_and_source_index_atomically() -> None:
    session = _FakeSession()
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)

    repository.persist_terminal_comparison(
        view=_view(result=_result()),
        created_at=timestamp,
        updated_at=timestamp,
        identity_labels={"identity-1": "管理员", "identity-2": "普通用户"},
    )

    assert [type(record) for record in session.merged] == [
        PermissionComparisonRecord,
        ExplorationKnowledgeSourceRecord,
    ]
    assert session.committed is True
    comparison_record = session.merged[0]
    assert comparison_record.identities_json["labels"]["identity-1"] == "管理员"  # type: ignore[union-attr]


def test_repository_rejects_comparison_without_result_before_transaction() -> None:
    session = _FakeSession()
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)

    with pytest.raises(PersistenceProjectionError, match="Persistence projection unavailable"):
        repository.persist_terminal_comparison(
            view=_view(result=None),
            created_at=timestamp,
            updated_at=timestamp,
        )

    assert session.merged == []
    assert session.committed is False


def test_repository_persists_nonterminal_comparison_index_without_result() -> None:
    session = _FakeSession()
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    view = PermissionComparisonView(
        comparison_id="comparison-1",
        state="created",
        identities={"identity-1": "created", "identity-2": "created"},
        result=None,
    )

    repository.persist_comparison_view(
        view=view,
        created_at=timestamp,
        updated_at=timestamp,
    )

    assert [type(record) for record in session.merged] == [PermissionComparisonRecord]
    assert session.merged[0].result_json is None  # type: ignore[union-attr]


class _FakeSession:
    def __init__(self) -> None:
        self.merged: list[object] = []
        self.committed = False

    def merge(self, record: object) -> object:
        self.merged.append(record)
        return record

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        raise AssertionError("terminal comparison should not roll back")

    def close(self) -> None:
        pass


def _view(*, result: PermissionComparisonResult | None) -> PermissionComparisonView:
    return PermissionComparisonView(
        comparison_id="comparison-1",
        state="completed",
        identities={"identity-1": "completed", "identity-2": "completed"},
        result=result,
    )


def _result() -> PermissionComparisonResult:
    return PermissionComparisonResult(
        comparison_id="comparison-1",
        status="completed",
        identities=[
            IdentityEvidenceBundle(identity_id="identity-1", state=IdentityRunState.COMPLETED),
            IdentityEvidenceBundle(identity_id="identity-2", state=IdentityRunState.COMPLETED),
        ],
    )
