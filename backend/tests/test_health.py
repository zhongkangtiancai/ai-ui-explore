from fastapi.testclient import TestClient

from ai_ui_explorer.main import create_app


def test_health_returns_service_metadata() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-ui-explorer-backend",
        "version": "0.1.0",
        "environment": "development",
    }


def test_unknown_route_uses_public_error_contract() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Resource not found",
        }
    }
