from __future__ import annotations

from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from ai_ui_explorer.api.routes.exploration_tasks import get_task_service
from ai_ui_explorer.exploration.authentication import (
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.login_runtime import HumanLoginSession
from ai_ui_explorer.exploration.queue import ExplorationBudget, ExplorationTarget
from ai_ui_explorer.exploration.runner import (
    ExplorationCancellationToken,
    ExplorationRunner,
)
from ai_ui_explorer.main import create_app
from ai_ui_explorer.permission_comparison.evidence import project_snapshot
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.snapshot.redaction import Redactor
from ai_ui_explorer.task_management.evidence import (
    ExplorationEvidenceExport,
    TaskPageView,
)
from ai_ui_explorer.task_management.models import (
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import (
    ExplorationTaskService,
    TaskServiceError,
    _TaskRuntimeContext,
)
from tests.snapshot.conftest import LoginSite
from tests.snapshot.factories import make_snapshot


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

    def pages(self, task_id: str) -> list[TaskPageView] | None:
        if self.get(task_id) is None:
            return None
        return [_page_view()]

    def page_detail(self, task_id: str, page_id: str):
        if self.get(task_id) is None or page_id != "page-1":
            return None
        return _page_evidence()

    def export(self, task_id: str) -> ExplorationEvidenceExport | None:
        if self.get(task_id) is None:
            return None
        return ExplorationEvidenceExport(
            schema_version="1.0",
            task_id=task_id,
            state="completed",
            result=self.summary.result,
            pages=[_page_view()],
        )


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


def test_pages_detail_and_export_are_safe_and_schema_valid(client: TestClient) -> None:
    pages = client.get("/api/v1/exploration-tasks/task-1/pages")
    assert pages.status_code == 200
    assert pages.json()[0]["page_id"] == "page-1"

    detail = client.get("/api/v1/exploration-tasks/task-1/pages/page-1")
    assert detail.status_code == 200
    assert detail.json()["elements"]

    exported = client.get("/api/v1/exploration-tasks/task-1/export")
    assert exported.headers["content-type"].startswith("application/json")
    assert "attachment; filename=exploration-evidence.json" in exported.headers[
        "content-disposition"
    ]
    assert "password" not in exported.text.lower()
    assert "cookie" not in exported.text.lower()


def test_unknown_task_and_page_use_fixed_safe_errors(client: TestClient) -> None:
    assert client.get("/api/v1/exploration-tasks/task-999/pages").status_code == 404
    assert client.get("/api/v1/exploration-tasks/task-1/pages/page-999").status_code == 404


def _page_evidence():
    return project_snapshot(
        target=ExplorationTarget(
            url="https://app.example.test/dashboard?token=fixture-secret",
            depth=0,
            source_url=None,
            module_id="dashboard",
            action_type="module_entry",
            label="Dashboard",
        ),
        snapshot=make_snapshot(),
        redactor=Redactor(),
    )


def _page_view() -> TaskPageView:
    page = _page_evidence()
    return TaskPageView(
        page_id="page-1",
        page_key=page.page_key,
        frame_count=1,
        element_count=len(page.elements),
        link_count=0,
        status="observed",
        evidence_refs=list(page.evidence_refs),
    )


def test_local_login_task_completes_after_confirmation(login_site: LoginSite) -> None:
    runtime_closed = Event()
    service = _local_login_service(login_site, runtime_closed)
    app = create_app()
    app.state.exploration_task_service = service

    with TestClient(app) as local_client:
        created = local_client.post(
            "/api/v1/exploration-tasks",
            json=_local_login_payload(login_site),
        )
        assert created.status_code == 202
        task_id = created.json()["task_id"]

        paused = _wait_for_task_state(local_client, task_id, "paused_for_human")
        assert paused["phase"] == "awaiting_human"

        confirmed = local_client.post(
            f"/api/v1/exploration-tasks/{task_id}/confirm-login"
        )
        assert confirmed.status_code == 200

        completed = _wait_for_task_state(local_client, task_id, "completed")
        assert completed["phase"] == "completed"
        result = local_client.get(f"/api/v1/exploration-tasks/{task_id}/result")
        assert result.status_code == 200
        assert result.json() == {
            "page_count": 1,
            "element_count": 2,
            "link_count": 1,
            "source_summary": "redacted source",
        }
        assert runtime_closed.wait(timeout=5)

        rejected_confirmation = local_client.post(
            f"/api/v1/exploration-tasks/{task_id}/confirm-login"
        )
        rejected_cancellation = local_client.post(
            f"/api/v1/exploration-tasks/{task_id}/cancel"
        )

    assert rejected_confirmation.status_code == 409
    assert rejected_cancellation.status_code == 409


def test_local_browser_task_exposes_redacted_page_and_locator_details(
    login_site: LoginSite,
) -> None:
    runtime_closed = Event()
    service = _local_login_service(login_site, runtime_closed)
    app = create_app()
    app.state.exploration_task_service = service

    with TestClient(app) as local_client:
        created = local_client.post(
            "/api/v1/exploration-tasks",
            json=_local_login_payload(login_site),
        )
        task_id = created.json()["task_id"]
        _wait_for_task_state(local_client, task_id, "paused_for_human")
        assert local_client.post(
            f"/api/v1/exploration-tasks/{task_id}/confirm-login"
        ).status_code == 200
        _wait_for_task_state(local_client, task_id, "completed")

        pages = local_client.get(f"/api/v1/exploration-tasks/{task_id}/pages")
        assert pages.status_code == 200
        assert len(pages.json()) == 1
        assert pages.json()[0]["page_id"] == "page-1"

        detail = local_client.get(
            f"/api/v1/exploration-tasks/{task_id}/pages/page-1"
        )
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["elements"]
        assert any(item["locator_candidates"] for item in payload["elements"])
        assert "fixture-password-do-not-return" not in str(payload)
        assert runtime_closed.wait(timeout=5)


def _local_login_service(
    login_site: LoginSite,
    runtime_closed: Event,
) -> ExplorationTaskService:
    class SimulatedHumanRuntime:
        def __init__(self, delegate: HumanLoginSession) -> None:
            self._delegate = delegate

        def start(self) -> None:
            self._delegate.start()
            browser = object.__getattribute__(self._delegate, "_browser")
            page = object.__getattribute__(browser, "_page")
            page.locator("#fixture-login").click()

        def confirm_and_verify(self) -> AuthenticationVerification:
            return self._delegate.confirm_and_verify()

        def collector_port(self) -> object:
            return self._delegate.collector_port()

        def close(self) -> None:
            self._delegate.close()
            runtime_closed.set()

    def runtime_factory(
        context: _TaskRuntimeContext,
        plan: AuthenticationPlan,
        policy: object,
    ) -> SimulatedHumanRuntime:
        browser = PlaywrightBrowserSession.open(headless=False)
        collector = context.create_session_collector(
            session=browser,
            limits=SnapshotLimits(),
        )
        runtime = context.create_human_login_session(
            plan=plan,
            policy=policy,  # type: ignore[arg-type]
            browser=browser,
            collector=collector,
        )
        return SimulatedHumanRuntime(runtime)

    def runner_factory(
        context: _TaskRuntimeContext,
        policy: object,
        budget: ExplorationBudget,
        collector: object,
        cancellation_token: ExplorationCancellationToken,
    ) -> ExplorationRunner:
        return context.create_runner(
            policy=policy,  # type: ignore[arg-type]
            budget=budget,
            collector=collector,
            cancellation_token=cancellation_token,
        )

    return ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=runtime_factory,  # type: ignore[arg-type]
        runner_factory=runner_factory,
    )


def _local_login_payload(login_site: LoginSite) -> dict[str, object]:
    return {
        "module_entry": {
            "module_id": "dashboard",
            "url": login_site.dashboard_url,
            "label": "Local dashboard",
        },
        "allowed_origins": [login_site.policy.allowed_origins[0]],
        "authentication_origins": [login_site.policy.authentication_origins[0]],
        "budget": {"max_pages": 1, "max_depth": 0, "max_queue_size": 1},
        "authentication_plan": {
            "authentication_url": login_site.login_url,
            "post_login_url_prefix": login_site.dashboard_url,
            "checkpoint_css_selector": "#signed-in-marker",
        },
        "allow_local_http": True,
    }


def _wait_for_task_state(
    client: TestClient,
    task_id: str,
    expected_state: str,
) -> dict[str, object]:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(f"/api/v1/exploration-tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["state"] == expected_state:
            return payload
        sleep(0.05)
    raise AssertionError(f"Task did not reach {expected_state}.")


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
