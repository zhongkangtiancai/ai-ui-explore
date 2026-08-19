from datetime import UTC, datetime

from ai_ui_explorer.persistence.models import PermissionComparisonRecord
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def test_repository_returns_valid_terminal_comparison_view() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(_record(state="completed"))  # type: ignore[arg-type]
    )

    view = repository.get_terminal_comparison_view("comparison-1")

    assert view is not None
    assert view.comparison_id == "comparison-1"
    assert view.result is not None
    assert view.result.status == "completed"
    assert repository.get_terminal_comparison_pages("comparison-1", "identity-1") == []
    assert repository.get_terminal_comparison_differences("comparison-1") == []
    export = repository.get_terminal_comparison_export("comparison-1")
    assert export is not None
    assert export.schema_version == "1.0"


def test_repository_rebuilds_comparison_knowledge_source_with_persisted_labels() -> None:
    record = _record(state="completed")
    record.identities_json = {
        "schema_version": "1.0",
        "states": {"identity-1": "completed", "identity-2": "completed"},
        "labels": {"identity-1": "管理员", "identity-2": "普通用户"},
    }
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(record)  # type: ignore[arg-type]
    )

    source = repository.get_terminal_comparison_knowledge_source("comparison-1")

    assert source is not None
    assert source.identity_labels["identity-1"] == "管理员"


def test_repository_hides_nonterminal_comparison_record() -> None:
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(_record(state="collecting"))  # type: ignore[arg-type]
    )

    assert repository.get_terminal_comparison_view("comparison-1") is None


def test_repository_returns_failed_interrupted_comparison_without_result() -> None:
    record = _record(state="failed")
    record.identities_json = {"identity-1": "failed", "identity-2": "failed"}
    record.result_json = None
    repository = SafeTaskRepository(
        session_factory=lambda: _FakeSession(record)  # type: ignore[arg-type]
    )

    view = repository.get_terminal_comparison_view("comparison-1")

    assert view is not None
    assert view.state == "failed"
    assert view.result is None


class _FakeSession:
    def __init__(self, record: PermissionComparisonRecord) -> None:
        self._record = record

    def get(self, _model: object, comparison_id: str) -> PermissionComparisonRecord | None:
        return self._record if comparison_id == self._record.comparison_id else None

    def close(self) -> None:
        pass


def _record(*, state: str) -> PermissionComparisonRecord:
    timestamp = datetime(2026, 8, 19, tzinfo=UTC)
    return PermissionComparisonRecord(
        comparison_id="comparison-1",
        state=state,
        created_at=timestamp,
        updated_at=timestamp,
        identities_json={"identity-1": "completed", "identity-2": "completed"},
        result_json={
            "comparison_id": "comparison-1",
            "status": "completed",
            "identities": [
                {"identity_id": "identity-1", "state": "completed", "pages": []},
                {"identity_id": "identity-2", "state": "completed", "pages": []},
            ],
            "differences": [],
        },
        schema_version="1.0",
    )
