from unittest.mock import Mock

from fastapi.testclient import TestClient

from ai_ui_explorer.core.config import Settings
from ai_ui_explorer.main import create_app
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def _app_for_test():
    return create_app(
        settings=Settings(
            database_url="postgresql://user:password@localhost:5432/explorer"
        ),
        persistence_repository=Mock(spec=SafeTaskRepository),
    )


def test_health_returns_service_metadata() -> None:
    client = TestClient(_app_for_test())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-ui-explorer-backend",
        "version": "0.1.0",
        "environment": "development",
    }


def test_unknown_route_uses_public_error_contract() -> None:
    client = TestClient(_app_for_test())

    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Resource not found",
        }
    }
