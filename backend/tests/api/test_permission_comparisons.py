"""Safe HTTP boundary tests for permission comparison runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from ai_ui_explorer.api.routes.permission_comparisons import (
    get_permission_comparison_service,
)
from ai_ui_explorer.exploration.authentication import (
    AuthenticationPlan,
    AuthenticationVerification,
)
from ai_ui_explorer.exploration.login_runtime import HumanLoginSession
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.runner import ExplorationCancellationToken, ExplorationRunner
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    PermissionComparisonExport,
    PermissionComparisonResult,
)
from ai_ui_explorer.permission_comparison.service import (
    PermissionComparisonServiceError,
    PermissionComparisonView,
)
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import ExplorationTaskService, _TaskRuntimeContext
from tests.api.app_factory import create_test_app

if TYPE_CHECKING:
    from tests.api.fixtures.permission_comparison_site import PermissionComparisonSite

pytest_plugins = ("tests.api.fixtures.permission_comparison_site",)


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
    app = create_test_app()
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


def test_local_multirole_comparison_reports_observed_admin_difference(
    permission_comparison_site: PermissionComparisonSite,
) -> None:
    app = _comparison_app(permission_comparison_site)
    with TestClient(app) as local_client:
        created = local_client.post(
            "/api/v1/permission-comparisons",
            json=_local_payload(permission_comparison_site),
        )
        assert created.status_code == 202
        comparison_id = created.json()["comparison_id"]
        _wait_for_comparison_state(local_client, comparison_id, "identity-1", "paused_for_human")
        permission_comparison_site.complete_login_for_current_visible_context("admin")
        assert local_client.post(
            f"/api/v1/permission-comparisons/{comparison_id}/identities/identity-1/confirm-login"
        ).status_code == 200
        _wait_for_comparison_state(local_client, comparison_id, "identity-2", "paused_for_human")
        permission_comparison_site.complete_login_for_current_visible_context("member")
        assert local_client.post(
            f"/api/v1/permission-comparisons/{comparison_id}/identities/identity-2/confirm-login"
        ).status_code == 200
        terminal = _wait_for_terminal_comparison(local_client, comparison_id)

    differences = terminal["result"]["differences"]
    difference = next(
        item
        for item in differences
        if item["identity_states"] == {
            "identity-1": "observed",
            "identity-2": "not_observed",
        }
    )
    assert terminal["state"] == "completed"
    assert difference["reliability"] == "high"
    assert permission_comparison_site.all_contexts_closed()


def test_restricted_identity_is_inconclusive_and_contexts_close(
    permission_comparison_site: PermissionComparisonSite,
) -> None:
    app = _comparison_app(permission_comparison_site)
    with TestClient(app) as local_client:
        created = local_client.post(
            "/api/v1/permission-comparisons",
            json=_local_payload(permission_comparison_site),
        )
        assert created.status_code == 202
        comparison_id = created.json()["comparison_id"]
        _wait_for_comparison_state(local_client, comparison_id, "identity-1", "paused_for_human")
        permission_comparison_site.complete_login_for_current_visible_context("admin")
        local_client.post(
            f"/api/v1/permission-comparisons/{comparison_id}/identities/identity-1/confirm-login"
        )
        _wait_for_comparison_state(local_client, comparison_id, "identity-2", "paused_for_human")
        permission_comparison_site.complete_login_for_current_visible_context("restricted")
        local_client.post(
            f"/api/v1/permission-comparisons/{comparison_id}/identities/identity-2/confirm-login"
        )
        terminal = _wait_for_terminal_comparison(local_client, comparison_id)

    assert terminal["state"] == "partial"
    assert all(item["reliability"] == "inconclusive" for item in terminal["result"]["differences"])
    assert permission_comparison_site.all_contexts_closed()


def _comparison_app(site: PermissionComparisonSite):
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
        budget: object,
        collector: object,
        cancellation_token: ExplorationCancellationToken,
    ) -> ExplorationRunner:
        return context.create_runner(
            policy=policy,
            budget=budget,  # type: ignore[arg-type]
            collector=collector,
            cancellation_token=cancellation_token,
        )

    task_service = ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=runtime_factory,
        runner_factory=runner_factory,
    )
    app = create_test_app(task_service=task_service)
    app.state.exploration_task_service = task_service
    from ai_ui_explorer.permission_comparison.service import PermissionComparisonService

    app.state.permission_comparison_service = PermissionComparisonService(task_service=task_service)
    return app


def _local_payload(site: PermissionComparisonSite) -> dict[str, object]:
    return {
        "module_entry": {"module_id": "dashboard", "url": site.dashboard_url},
        "allowed_origins": [site.origin],
        "authentication_origins": [site.origin],
        "budget": {"max_pages": 2, "max_depth": 1, "max_queue_size": 2},
        "allow_local_http": True,
        "identities": [
            {
                "identity_id": "identity-1",
                "label": "管理员",
                "authentication_plan": {
                    "authentication_url": site.login_url,
                    "post_login_url_prefix": site.dashboard_url,
                    "checkpoint_css_selector": "#signed-in-marker",
                },
            },
            {
                "identity_id": "identity-2",
                "label": "普通用户",
                "authentication_plan": {
                    "authentication_url": site.login_url,
                    "post_login_url_prefix": site.dashboard_url,
                    "checkpoint_css_selector": "#signed-in-marker",
                },
            },
        ],
    }


def _wait_for_comparison_state(
    client: TestClient,
    comparison_id: str,
    identity_id: str,
    expected_state: str,
) -> None:
    from time import monotonic, sleep

    deadline = monotonic() + 30
    while monotonic() < deadline:
        response = client.get(f"/api/v1/permission-comparisons/{comparison_id}")
        assert response.status_code == 200
        if response.json()["identities"][identity_id] == expected_state:
            return
        sleep(0.05)
    raise AssertionError("comparison did not reach expected identity state")


def _wait_for_terminal_comparison(client: TestClient, comparison_id: str) -> dict[str, object]:
    from time import monotonic, sleep

    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(f"/api/v1/permission-comparisons/{comparison_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["state"] in {"completed", "partial", "cancelled"}:
            return payload
        sleep(0.05)
    raise AssertionError("comparison did not reach terminal state")
