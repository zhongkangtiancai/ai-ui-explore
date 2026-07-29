"""Local two-origin HTTP fixtures for real-browser snapshot tests."""

from __future__ import annotations

from collections.abc import Generator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote

import pytest

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "snapshot_site"


class _QuietFixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Keep successful browser fixture requests out of the test output."""


def _serve(directory: Path) -> tuple[ThreadingHTTPServer, Thread]:
    handler = partial(_QuietFixtureHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture(scope="session")
def secondary_url() -> Generator[str]:
    server, thread = _serve(_FIXTURE_ROOT / "secondary")
    try:
        yield f"http://127.0.0.1:{server.server_port}/cross-frame.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(scope="session")
def primary_url(secondary_url: str) -> Generator[str]:
    server, thread = _serve(_FIXTURE_ROOT / "primary")
    try:
        encoded_secondary = quote(secondary_url, safe="")
        yield f"http://127.0.0.1:{server.server_port}/index.html?secondary={encoded_secondary}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
