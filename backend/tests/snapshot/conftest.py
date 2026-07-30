"""Local two-origin HTTP fixtures for real-browser snapshot tests."""

from __future__ import annotations

from collections.abc import Generator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import sleep
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import pytest

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "snapshot_site"


class _QuietFixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Keep successful browser fixture requests out of the test output."""

    def do_GET(self) -> None:
        parsed_url = urlsplit(self.path)
        delay_values = parse_qs(parsed_url.query).get("response_delay_ms", [])
        if parsed_url.path == "/slow-frame.html":
            busy_values = parse_qs(parsed_url.query).get("busy_ms", ["3000"])
            busy_ms = int(busy_values[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                (
                    "<!doctype html><html><head><meta charset='utf-8'></head><body>"
                    f"<script>const end=performance.now()+{busy_ms};"
                    "while(performance.now()<end){}</script>"
                    "<button>预算边界按钮</button></body></html>"
                ).encode()
            )
            return
        if delay_values:
            sleep(int(delay_values[0]) / 1_000)
        super().do_GET()


def _serve(directory: Path) -> tuple[ThreadingHTTPServer, Thread]:
    handler = partial(_QuietFixtureHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    try:
        thread.start()
    except BaseException:
        _stop_server(server, thread, started=False)
        raise
    return server, thread


def _stop_server(
    server: ThreadingHTTPServer,
    thread: Thread,
    *,
    started: bool,
) -> None:
    if not started:
        server.server_close()
        return
    try:
        server.shutdown()
    finally:
        try:
            server.server_close()
        finally:
            thread.join()


@pytest.fixture(scope="session")
def secondary_url() -> Generator[str]:
    server, thread = _serve(_FIXTURE_ROOT / "secondary")
    try:
        yield f"http://127.0.0.1:{server.server_port}/cross-frame.html"
    finally:
        _stop_server(server, thread, started=True)


@pytest.fixture(scope="session")
def primary_url(secondary_url: str) -> Generator[str]:
    server, thread = _serve(_FIXTURE_ROOT / "primary")
    try:
        encoded_secondary = quote(secondary_url, safe="")
        yield f"http://127.0.0.1:{server.server_port}/index.html?secondary={encoded_secondary}"
    finally:
        _stop_server(server, thread, started=True)


@pytest.fixture(scope="session")
def locator_page_url(primary_url: str) -> str:
    query = urlsplit(primary_url).query
    return urljoin(primary_url, f"/locator-candidates.html?{query}")
