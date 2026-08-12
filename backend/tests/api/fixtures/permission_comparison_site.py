"""Local fictional role site used only by permission-comparison E2E tests."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit

import pytest

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


class _RoleHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        role = parse_qs(parsed.query).get("role", [""])[0]
        if parsed.path == "/login-complete":
            self.send_response(302)
            self.send_header("Set-Cookie", f"fixture_role={role}; Path=/")
            self.send_header("Location", "/dashboard.html")
            self.end_headers()
            return
        if parsed.path == "/collector-failure.html":
            self.connection.close()
            return
        role = _cookie_role(self.headers.get("Cookie", ""))
        body = _page(parsed.path, role)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def _page(path: str, role: str) -> str:
    if path == "/login.html":
        return (
            "<!doctype html>"
            "<button id='login-admin' "
            "onclick=\"location='/login-complete?role=admin'\">Admin</button>"
            "<button id='login-member' "
            "onclick=\"location='/login-complete?role=member'\">Member</button>"
            "<button id='login-restricted' "
            "onclick=\"location='/login-complete?role=restricted'\">Restricted</button>"
        )
    if path == "/admin.html" and role == "admin":
        return "<!doctype html><main id='signed-in-marker'><h1>Admin console</h1></main>"
    links = "<a href='/admin.html'>Admin console</a>" if role == "admin" else ""
    if role == "restricted":
        links = "<a href='/collector-failure.html'>Restricted area</a>"
    return f"<!doctype html><main id='signed-in-marker'><h1>Dashboard {role}</h1>{links}</main>"


def _cookie_role(cookie_header: str) -> str:
    for item in cookie_header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == "fixture_role":
            return value
    return ""


@pytest.fixture
def permission_comparison_site() -> Generator[PermissionComparisonSite]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RoleHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
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
        server.shutdown()
        server.server_close()
        thread.join()
