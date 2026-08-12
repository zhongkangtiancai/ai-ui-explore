"""Safe HTTP boundary tests for permission comparison runs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_ui_explorer.api.routes.permission_comparisons import (
    get_permission_comparison_service,
)
from ai_ui_explorer.main import create_app
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    PermissionComparisonExport,
    PermissionComparisonResult,
)
from ai_ui_explorer.permission_comparison.service import (
    PermissionComparisonServiceError,
    PermissionComparisonView,
)


def _payload() -> dict[str, object]:
    return {
        "module_entry": {
            "module_id": "dashboard",
            "url": "https://app.example.test/dashboard",
        },
        "allowed_origins": ["https://app.example.test"],
        "authentication_origins": ["https://sso.example.test"],
        "budget": {"max_pages": 1, "max_depth": 0, "max_queue_size": 1},
        "identities": [
            {
                "identity_id": "identity-1",
                "label": "管理员",
                "authentication_plan": _authentication_plan(),
            },
            {
                "identity_id": "identity-2",
                "label": "普通用户",
                "authentication_plan": _authentication_plan(),
            },
        ],
    }


def _authentication_plan() -> dict[str, str]:
    return {
        "authentication_url": "https://sso.example.test/login",
        "post_login_url_prefix": "https://app.example.test/dashboard",
        "checkpoint_css_selector": "#signed-in-marker",
    }


class _FakeComparisonService:
    def __init__(self) -> None:
        self.created: list[object] = []
        self.view = PermissionComparisonView(
            comparison_id="comparison-1",
            state="completed",
            identities={"identity-1": "completed", "identity-2": "completed"},
            result=_result(),
        )

    def create(self, command: object) -> PermissionComparisonView:
        self.created.append(command)
        return self.view

    def get(self, comparison_id: str) -> PermissionComparisonView:
        if comparison_id != self.view.comparison_id:
            raise RuntimeError("unknown comparison")
        return self.view

    def pages(self, comparison_id: str, identity_id: str) -> list[object]:
        self.get(comparison_id)
        if identity_id not in self.view.identities:
            raise PermissionComparisonServiceError("Comparison was not found.")
        return []

    def page_detail(self, comparison_id: str, identity_id: str, page_key: str) -> object:
        del identity_id, page_key
        self.get(comparison_id)
        raise PermissionComparisonServiceError("Comparison was not found.")

    def differences(self, comparison_id: str) -> list[object]:
        return list(self.get(comparison_id).result.differences)  # type: ignore[union-attr]

    def export(self, comparison_id: str) -> PermissionComparisonExport:
        result = self.get(comparison_id).result
        assert result is not None
        return PermissionComparisonExport(**result.model_dump(mode="json"))

    def confirm_login(self, comparison_id: str, identity_id: str) -> PermissionComparisonView:
        del identity_id
        return self.get(comparison_id)

    def cancel(self, comparison_id: str) -> PermissionComparisonView:
        return self.get(comparison_id)


def _result() -> PermissionComparisonResult:
    return PermissionComparisonResult(
        comparison_id="comparison-1",
        status="completed",
        identities=[
            IdentityEvidenceBundle(identity_id="identity-1", state="completed"),
            IdentityEvidenceBundle(identity_id="identity-2", state="completed"),
        ],
        differences=[],
    )


@pytest.fixture
def comparison_service() -> _FakeComparisonService:
    return _FakeComparisonService()


@pytest.fixture
def client(comparison_service: _FakeComparisonService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_permission_comparison_service] = (
        lambda: comparison_service
    )
    return TestClient(app)


def test_create_comparison_and_read_safe_detail(
    client: TestClient,
    comparison_service: _FakeComparisonService,
) -> None:
    created = client.post("/api/v1/permission-comparisons", json=_payload())

    assert created.status_code == 202
    assert created.json()["comparison_id"] == "comparison-1"
    assert len(comparison_service.created) == 1
    detail = client.get("/api/v1/permission-comparisons/comparison-1")
    assert detail.status_code == 200
    assert "cookie" not in detail.text.lower()
    assert "token" not in detail.text.lower()


@pytest.mark.parametrize("field", ["password", "token", "cookie", "storage_state"])
def test_create_rejects_credentials_without_echoing_them(
    client: TestClient,
    field: str,
) -> None:
    response = client.post(
        "/api/v1/permission-comparisons",
        json={**_payload(), field: "secret"},
    )

    assert response.status_code == 422
    assert field not in response.text.lower()


def test_export_is_attachment_and_never_contains_browser_data(client: TestClient) -> None:
    response = client.get("/api/v1/permission-comparisons/comparison-1/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"] == (
        'attachment; filename="permission-comparison.json"'
    )
    assert response.json()["schema_version"] == "1.0"
    assert "storage_state" not in response.text.lower()
    assert "browser" not in response.text.lower()


def test_page_detail_requires_known_identity_and_known_page(client: TestClient) -> None:
    response = client.get(
        "/api/v1/permission-comparisons/comparison-1/"
        "pages/https%3A%2F%2Fapp.example.test%2Fdashboard",
        params={"identity_id": "identity-1"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "comparison_not_found",
            "message": "Comparison not found",
        }
    }
