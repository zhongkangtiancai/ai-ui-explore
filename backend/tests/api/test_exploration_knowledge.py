"""HTTP contracts for unified exploration knowledge package downloads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ai_ui_explorer.exploration_knowledge.models import (
    ComparisonKnowledgeSource,
    TaskKnowledgeSource,
)
from ai_ui_explorer.exploration_knowledge.service import (
    ExplorationKnowledgeExportService,
)
from ai_ui_explorer.main import create_app
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityRunState,
    PermissionComparisonResult,
)


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.state.exploration_knowledge_export_service = ExplorationKnowledgeExportService(
        task_service=_TaskSources(),
        comparison_service=_ComparisonSources(),
    )
    return TestClient(app)


def test_sources_route_lists_safe_terminal_task_and_comparison_sources(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/exploration-knowledge-packages/sources")

    assert response.status_code == 200
    assert [item["source_id"] for item in response.json()] == [
        "comparison-1",
        "task-1",
    ]
    assert "authentication_plan" not in response.text


def test_export_route_returns_schema_valid_task_and_comparison_package(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/exploration-knowledge-packages/export",
        json={"task_ids": ["task-1"], "comparison_ids": ["comparison-1"]},
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="exploration-knowledge-package.json"'
    )
    body = response.json()
    assert body["schema_version"] == "2.0"
    assert {item["source_id"] for item in body["sources"]} == {
        "task-1",
        "comparison-1",
    }
    assert "fixture-password-do-not-return" not in response.text


@pytest.mark.parametrize(
    ("payload", "status_code", "code"),
    [
        ({}, 422, "invalid_request"),
        ({"task_ids": ["task-999"]}, 404, "source_not_found"),
        ({"task_ids": ["task-1"], "token": "x"}, 422, "invalid_request"),
    ],
)
def test_export_route_returns_fixed_safe_errors(
    client: TestClient,
    payload: dict[str, object],
    status_code: int,
    code: str,
) -> None:
    response = client.post("/api/v1/exploration-knowledge-packages/export", json=payload)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "token" not in response.text


class _TaskSources:
    def list_summaries(self) -> list[object]:
        return [SimpleNamespace(task_id="task-1")]

    def knowledge_source(self, task_id: str) -> TaskKnowledgeSource | None:
        if task_id == "task-1":
            return TaskKnowledgeSource(source_id="task-1", state="completed")
        return None


class _ComparisonSources:
    def list_views(self) -> list[object]:
        return [SimpleNamespace(comparison_id="comparison-1")]

    def knowledge_source(self, comparison_id: str) -> ComparisonKnowledgeSource | None:
        if comparison_id == "comparison-1":
            return ComparisonKnowledgeSource(
                source_id="comparison-1",
                result=PermissionComparisonResult(
                    comparison_id="comparison-1",
                    status="partial",
                    identities=[
                        IdentityEvidenceBundle(
                            identity_id="identity-1",
                            state=IdentityRunState.COMPLETED,
                        ),
                        IdentityEvidenceBundle(
                            identity_id="identity-2",
                            state=IdentityRunState.PARTIAL,
                        ),
                    ],
                ),
            )
        return None
