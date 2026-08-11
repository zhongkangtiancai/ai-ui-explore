from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from ai_ui_explorer.api.routes.exploration_tasks import get_task_service
from ai_ui_explorer.main import create_app
from ai_ui_explorer.task_management.models import (
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)
from ai_ui_explorer.task_management.service import TaskServiceError


def valid_payload() -> dict[str, object]:
    return {
        "module_entry": {
            "module_id": "dashboard",
            "url": "https://app.example.test/dashboard",
            "label": "Dashboard",
        },
        "allowed_origins": ["https://app.example.test"],
        "authentication_origins": [],
        "budget": {"max_pages": 1, "max_depth": 0, "max_queue_size": 1},
        "allow_local_http": False,
    }


class _FakeTaskService:
    def __init__(self) -> None:
        self.created_commands: list[object] = []
        self.summary = _summary()

    def create(self, command: object) -> TaskSummary:
        self.created_commands.append(command)
        return self.summary

    def get(self, task_id: str) -> TaskSummary | None:
        return self.summary if task_id == self.summary.task_id else None

    def events(self, task_id: str) -> list[TaskEventView] | None:
        summary = self.get(task_id)
        return list(summary.events) if summary is not None else None

    def confirm_login(self, task_id: str) -> TaskSummary:
        if self.get(task_id) is None:
            raise TaskServiceError("Task was not found.")
        raise TaskServiceError("Task cannot confirm login.")

    def cancel(self, task_id: str) -> TaskSummary:
        if self.get(task_id) is None:
            raise TaskServiceError("Task was not found.")
        return self.summary

    def result(self, task_id: str) -> TaskResultSummary | None:
        summary = self.get(task_id)
        return summary.result if summary is not None else None


@pytest.fixture
def fake_service() -> _FakeTaskService:
    return _FakeTaskService()


@pytest.fixture
def client(fake_service: _FakeTaskService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: fake_service
    return TestClient(app)


def test_create_and_read_task_returns_safe_schema(
    client: TestClient,
    fake_service: _FakeTaskService,
) -> None:
    created = client.post("/api/v1/exploration-tasks", json=valid_payload())

    assert created.status_code == 202
    assert "cookie" not in created.text.lower()
    assert "token" not in created.text.lower()
    assert len(fake_service.created_commands) == 1
    task_id = created.json()["task_id"]

    read = client.get(f"/api/v1/exploration-tasks/{task_id}")
    assert read.status_code == 200
    assert read.json()["phase"] == "created"


def test_unknown_task_uses_fixed_error(client: TestClient) -> None:
    response = client.get("/api/v1/exploration-tasks/task-999")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "task_not_found",
        "message": "Task not found",
    }


def test_events_result_cancel_and_illegal_confirmation_use_safe_contracts(
    client: TestClient,
) -> None:
    assert client.get("/api/v1/exploration-tasks/task-1/events").json() == {
        "events": [
            {
                "event_type": "task_created",
                "reason_code": None,
                "checkpoint_id": None,
                "occurred_at": "2026-08-11T00:00:00Z",
            }
        ]
    }
    assert client.get("/api/v1/exploration-tasks/task-1/result").json() == {
        "page_count": 0,
        "element_count": 0,
        "link_count": 0,
        "source_summary": "redacted source",
    }
    assert client.post("/api/v1/exploration-tasks/task-1/cancel").status_code == 200

    response = client.post("/api/v1/exploration-tasks/task-1/confirm-login")
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "task_state_invalid",
            "message": "Task operation is not allowed",
        }
    }


def test_create_rejects_sensitive_or_unknown_fields_with_fixed_error(
    client: TestClient,
) -> None:
    payload = valid_payload()
    payload["password"] = "not-accepted"

    response = client.post("/api/v1/exploration-tasks", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed",
        }
    }
    assert "password" not in response.text.lower()


@pytest.mark.parametrize("operation", ["confirm-login", "cancel"])
@pytest.mark.parametrize(
    "body",
    [
        {"token": "not-accepted"},
        {"cookie": "not-accepted"},
        {"unexpected": "not-accepted"},
    ],
)
def test_task_operations_reject_any_request_body_fields(
    client: TestClient,
    operation: str,
    body: dict[str, str],
) -> None:
    response = client.post(
        f"/api/v1/exploration-tasks/task-1/{operation}",
        json=body,
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed",
        }
    }
    assert next(iter(body)) not in response.text.lower()


def test_post_cors_preflight_allows_the_task_api(client: TestClient) -> None:
    response = client.options(
        "/api/v1/exploration-tasks",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


def _summary() -> TaskSummary:
    occurred_at = datetime(2026, 8, 11, tzinfo=UTC)
    return TaskSummary(
        task_id="task-1",
        state="created",
        phase="created",
        created_at=occurred_at,
        updated_at=occurred_at,
        redaction_count=0,
        events=[
            TaskEventView(
                event_type="task_created",
                occurred_at=occurred_at,
            )
        ],
        result=TaskResultSummary(
            page_count=0,
            element_count=0,
            link_count=0,
            source_summary="redacted source",
        ),
    )
