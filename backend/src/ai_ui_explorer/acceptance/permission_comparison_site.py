"""Loopback-only fictional role site for permission-comparison acceptance."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

_LOOPBACK_HOST = "127.0.0.1"
_ROLES = frozenset({"admin", "member", "restricted"})
_ROLE_COOKIE = "fixture_role"


class PermissionAcceptanceSite:
    """Serve fixed fictional roles on loopback without reading any credentials."""

    def __init__(self, *, port: int = 9100) -> None:
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def origin(self) -> str:
        """Return the local origin after the site has started."""
        server = self._require_server()
        return f"http://{_LOOPBACK_HOST}:{server.server_port}"

    @property
    def login_url(self) -> str:
        """Return the fixed fictional login page."""
        return f"{self.origin}/login.html"

    @property
    def dashboard_url(self) -> str:
        """Return the fixed protected dashboard page."""
        return f"{self.origin}/dashboard.html"

    def start(self) -> None:
        """Start one server bound only to IPv4 loopback."""
        if self._server is not None:
            return
        server = ThreadingHTTPServer((_LOOPBACK_HOST, self._port), _RoleHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread

    def close(self) -> None:
        """Stop the local server and join its serving thread."""
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join()

    def __enter__(self) -> PermissionAcceptanceSite:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_server(self) -> ThreadingHTTPServer:
        if self._server is None:
            raise RuntimeError("Permission acceptance site is not running.")
        return self._server


class _RoleHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        """Keep the local fixture quiet during acceptance runs."""

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/login.html":
            self._send_html(_login_page())
            return
        if parsed.path == "/login-complete":
            self._complete_login()
            return
        if parsed.path == "/collector-failure.html":
            self.connection.close()
            return

        role = _cookie_role(self.headers.get("Cookie", ""))
        if role not in _ROLES:
            self._redirect("/login.html")
            return
        if parsed.path == "/dashboard.html":
            self._send_html(_dashboard_page(role))
            return
        if parsed.path == "/admin.html" and role == "admin":
            self._send_html(
                "<!doctype html><main id='signed-in-marker'><h1>Admin console</h1></main>"
            )
            return
        if parsed.path == "/details.html":
            self._send_html(_details_page())
            return
        self.send_error(404)

    def _complete_login(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        role = query.get("role", [""])[0]
        if role not in _ROLES:
            self.send_error(400)
            return
        self.send_response(302)
        self.send_header("Set-Cookie", f"{_ROLE_COOKIE}={role}; Path=/")
        self.send_header("Location", "/dashboard.html")
        self.end_headers()

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(self, body: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def _login_page() -> str:
    return (
        "<!doctype html>"
        "<button id='login-admin' onclick=\"location='/login-complete?role=admin'\">Admin</button>"
        "<button id='login-member' "
        "onclick=\"location='/login-complete?role=member'\">Member</button>"
        "<button id='login-restricted' "
        "onclick=\"location='/login-complete?role=restricted'\">Restricted</button>"
    )


def _dashboard_page(role: str) -> str:
    links = "<a href='/admin.html'>Admin console</a>" if role == "admin" else ""
    if role == "restricted":
        links = "<a href='/collector-failure.html'>Restricted area</a>"
    readonly_controls = ""
    role_only = ""
    if role == "admin":
        readonly_controls = (
            "<button id='overview-tab' role='tab' aria-selected='true' "
            "onclick=\"document.querySelector('#tab-content').textContent='Overview selected'\">"
            "Overview</button><a id='view-details' href='/details.html'>查看详情</a>"
            "<button id='dangerous-submit' type='submit'>提交订单</button>"
            "<p id='tab-content'>Initial overview</p>"
        )
        role_only = "<p id='admin-only'>Admin-only observation</p>"
    return (
        f"<!doctype html><main id='signed-in-marker'><h1>Dashboard {role}</h1>"
        f"{readonly_controls}{role_only}{links}</main>"
    )


def _details_page() -> str:
    return (
        "<!doctype html><main id='signed-in-marker'><h1>Readonly details</h1>"
        "<p>Observed fixture detail only</p></main>"
    )


def _cookie_role(cookie_header: str) -> str:
    for item in cookie_header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == _ROLE_COOKIE:
            return value
    return ""
