from datetime import UTC, datetime

from ai_ui_explorer.persistence.dtos import PersistedComparisonIdentityMetadata
from ai_ui_explorer.persistence.models import PermissionComparisonRecord
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def test_repository_interrupts_nonterminal_comparisons_without_conclusion() -> None:
    record = PermissionComparisonRecord(
        comparison_id="comparison-1",
        state="paused_for_human",
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        updated_at=datetime(2026, 8, 19, tzinfo=UTC),
        identities_json={"identity-1": "paused_for_human", "identity-2": "created"},
        result_json=None,
        schema_version="1.0",
    )
    session = _FakeSession([record])
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]

    interrupted_ids = repository.interrupt_nonterminal_comparisons(
        occurred_at=datetime(2026, 8, 20, tzinfo=UTC)
    )

    assert interrupted_ids == ["comparison-1"]
    assert record.state == "failed"
    assert record.result_json is None
    assert record.identities_json == {"identity-1": "failed", "identity-2": "failed"}
    assert session.committed is True


def test_repository_interrupts_new_format_comparison_without_losing_identity_labels() -> None:
    record = PermissionComparisonRecord(
        comparison_id="comparison-2",
        state="paused_for_human",
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        updated_at=datetime(2026, 8, 19, tzinfo=UTC),
        identities_json=PersistedComparisonIdentityMetadata(
            schema_version="1.0",
            states={"identity-1": "paused_for_human", "identity-2": "created"},
            labels={"identity-1": "管理员", "identity-2": "普通用户"},
        ).model_dump(mode="json"),
        result_json=None,
        schema_version="1.0",
    )
    session = _FakeSession([record])
    repository = SafeTaskRepository(session_factory=lambda: session)  # type: ignore[arg-type]

    repository.interrupt_nonterminal_comparisons(
        occurred_at=datetime(2026, 8, 20, tzinfo=UTC)
    )

    assert record.state == "failed"
    assert record.identities_json == {
        "schema_version": "1.0",
        "states": {"identity-1": "failed", "identity-2": "failed"},
        "labels": {"identity-1": "管理员", "identity-2": "普通用户"},
    }


class _FakeScalarResult:
    def __init__(self, records: list[PermissionComparisonRecord]) -> None:
        self._records = records

    def all(self) -> list[PermissionComparisonRecord]:
        return self._records


class _FakeSession:
    def __init__(self, records: list[PermissionComparisonRecord]) -> None:
        self._records = records
        self.committed = False

    def scalars(self, _statement: object) -> _FakeScalarResult:
        return _FakeScalarResult(self._records)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        raise AssertionError("comparison recovery should not roll back")

    def close(self) -> None:
        pass
