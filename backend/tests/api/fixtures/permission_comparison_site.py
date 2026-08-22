"""Local fictional role site used only by permission-comparison E2E tests."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from threading import Lock

import pytest

from ai_ui_explorer.acceptance.permission_comparison_site import (
    PermissionAcceptanceSite as RunningPermissionAcceptanceSite,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy


@dataclass
class PermissionComparisonSite:
    origin: str
    policy: NavigationPolicy
    browsers: list[object] = field(default_factory=list)
    _selected_roles: list[str] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    @property
    def login_url(self) -> str:
        return f"{self.origin}/login.html"

    @property
    def dashboard_url(self) -> str:
        return f"{self.origin}/dashboard.html"

    def complete_login_for_current_visible_context(self, role: str) -> None:
        """Queue a fictional role selection; owner thread performs the click."""
        with self._lock:
            self._selected_roles.append(role)

    def consume_selected_role(self) -> str:
        with self._lock:
            if not self._selected_roles:
                raise AssertionError("test did not select a fictional role")
            return self._selected_roles.pop(0)

    def all_contexts_closed(self) -> bool:
        return all(bool(object.__getattribute__(browser, "_closed")) for browser in self.browsers)


@pytest.fixture
def permission_comparison_site() -> Generator[PermissionComparisonSite]:
    acceptance_site = RunningPermissionAcceptanceSite(port=0)
    acceptance_site.start()
    origin = acceptance_site.origin
    site = PermissionComparisonSite(
        origin=origin,
        policy=NavigationPolicy(
            allowed_origins=[origin],
            authentication_origins=[origin],
            allow_local_http=True,
        ),
    )
    try:
        yield site
    finally:
        acceptance_site.close()
