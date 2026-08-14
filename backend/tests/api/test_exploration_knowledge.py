"""HTTP contracts for unified exploration knowledge package downloads."""

from __future__ import annotations

from time import monotonic, sleep
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from ai_ui_explorer.exploration.authentication import AuthenticationPlan, AuthenticationVerification
from ai_ui_explorer.exploration.login_runtime import HumanLoginSession
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget
from ai_ui_explorer.exploration.runner import ExplorationCancellationToken, ExplorationRunner
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
from ai_ui_explorer.permission_comparison.service import PermissionComparisonService
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import ExplorationTaskService, _TaskRuntimeContext

if TYPE_CHECKING:
    from tests.api.fixtures.permission_comparison_site import PermissionComparisonSite

pytest_plugins = ("tests.api.fixtures.permission_comparison_site",)


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


def test_local_task_and_comparison_export_one_redacted_knowledge_package(
    permission_comparison_site: PermissionComparisonSite,
) -> None:
    app = _local_role_app(permission_comparison_site)
    with TestClient(app) as local_client:
        task_id = _complete_task(local_client, permission_comparison_site)
        comparison_id = _complete_comparison(local_client, permission_comparison_site)
        response = local_client.post(
            "/api/v1/exploration-knowledge-packages/export",
            json={"task_ids": [task_id], "comparison_ids": [comparison_id]},
        )

    assert response.status_code == 200
    exported = response.json()
    assert exported["pages"]
    assert exported["visibility_differences"]
    assert exported["inferences"] == []
    assert "fixture_role" not in response.text
    assert "cookie" not in response.text.lower()


def _local_role_app(site: PermissionComparisonSite):
    class SimulatedRoleRuntime:
        def __init__(self, delegate: HumanLoginSession) -> None:
            self._delegate = delegate

        def start(self) -> None:
            self._delegate.start()

        def confirm_and_verify(self) -> AuthenticationVerification:
            browser = object.__getattribute__(self._delegate, "_browser")
            page = object.__getattribute__(browser, "_page")
            page.locator(f"#login-{site.consume_selected_role()}").click()
            return self._delegate.confirm_and_verify()

        def collector_port(self) -> object:
            return self._delegate.collector_port()

        def close(self) -> None:
            self._delegate.close()

    def runtime_factory(
        context: _TaskRuntimeContext,
        plan: AuthenticationPlan,
        policy: NavigationPolicy,
    ) -> SimulatedRoleRuntime:
        browser = PlaywrightBrowserSession.open(headless=False)
        site.browsers.append(browser)
        collector = context.create_session_collector(session=browser, limits=SnapshotLimits())
        runtime = context.create_human_login_session(
            plan=plan,
            policy=policy,
            browser=browser,
            collector=collector,
        )
        return SimulatedRoleRuntime(runtime)

    def runner_factory(
        context: _TaskRuntimeContext,
        policy: NavigationPolicy,
        budget: ExplorationBudget,
        collector: object,
        cancellation_token: ExplorationCancellationToken,
    ) -> ExplorationRunner:
        return context.create_runner(
            policy=policy,
            budget=budget,
            collector=collector,
            cancellation_token=cancellation_token,
        )

    task_service = ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=runtime_factory,
        runner_factory=runner_factory,
    )
    comparison_service = PermissionComparisonService(task_service=task_service)
    app = create_app()
    app.state.exploration_task_service = task_service
    app.state.permission_comparison_service = comparison_service
    app.state.exploration_knowledge_export_service = ExplorationKnowledgeExportService(
        task_service=task_service,
        comparison_service=comparison_service,
    )
    return app


def _complete_task(client: TestClient, site: PermissionComparisonSite) -> str:
    created = client.post(
        "/api/v1/exploration-tasks",
        json=_task_payload(site),
    )
    assert created.status_code == 202
    task_id = created.json()["task_id"]
    _wait_for_task_state(client, task_id, "paused_for_human")
    site.complete_login_for_current_visible_context("admin")
    assert client.post(f"/api/v1/exploration-tasks/{task_id}/confirm-login").status_code == 200
    _wait_for_task_state(client, task_id, "completed")
    return task_id


def _complete_comparison(client: TestClient, site: PermissionComparisonSite) -> str:
    created = client.post("/api/v1/permission-comparisons", json=_comparison_payload(site))
    assert created.status_code == 202
    comparison_id = created.json()["comparison_id"]
    for identity_id, role in (("identity-1", "admin"), ("identity-2", "member")):
        _wait_for_identity_state(client, comparison_id, identity_id, "paused_for_human")
        site.complete_login_for_current_visible_context(role)
        assert client.post(
            f"/api/v1/permission-comparisons/{comparison_id}/identities/{identity_id}/confirm-login"
        ).status_code == 200
    _wait_for_comparison_state(client, comparison_id, "completed")
    return comparison_id


def _task_payload(site: PermissionComparisonSite) -> dict[str, object]:
    return {
        "module_entry": {"module_id": "dashboard", "url": site.dashboard_url},
        "allowed_origins": [site.origin],
        "authentication_origins": [site.origin],
        "budget": {"max_pages": 2, "max_depth": 1, "max_queue_size": 2},
        "authentication_plan": _authentication_plan(site),
        "allow_local_http": True,
    }


def _comparison_payload(site: PermissionComparisonSite) -> dict[str, object]:
    payload = _task_payload(site)
    payload.pop("authentication_plan")
    return {
        **payload,
        "identities": [
            {
                "identity_id": "identity-1",
                "label": "管理员",
                "authentication_plan": _authentication_plan(site),
            },
            {
                "identity_id": "identity-2",
                "label": "成员",
                "authentication_plan": _authentication_plan(site),
            },
        ],
    }


def _authentication_plan(site: PermissionComparisonSite) -> dict[str, str]:
    return {
        "authentication_url": site.login_url,
        "post_login_url_prefix": site.dashboard_url,
        "checkpoint_css_selector": "#signed-in-marker",
    }


def _wait_for_task_state(client: TestClient, task_id: str, expected: str) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(f"/api/v1/exploration-tasks/{task_id}")
        if response.status_code == 200 and response.json()["state"] == expected:
            return
        sleep(0.05)
    raise AssertionError(f"task did not reach {expected}")


def _wait_for_identity_state(
    client: TestClient,
    comparison_id: str,
    identity_id: str,
    expected: str,
) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(f"/api/v1/permission-comparisons/{comparison_id}")
        if response.status_code == 200 and response.json()["identities"][identity_id] == expected:
            return
        sleep(0.05)
    raise AssertionError(f"identity did not reach {expected}")


def _wait_for_comparison_state(client: TestClient, comparison_id: str, expected: str) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(f"/api/v1/permission-comparisons/{comparison_id}")
        if response.status_code == 200 and response.json()["state"] == expected:
            return
        sleep(0.05)
    raise AssertionError(f"comparison did not reach {expected}")


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
