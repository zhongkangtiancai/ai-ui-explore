"""Shared local-browser fixtures used across backend acceptance tests."""

from tests.snapshot.conftest import (
    locator_page_url,
    login_site,
    primary_url,
    secondary_url,
)

__all__ = ["locator_page_url", "login_site", "primary_url", "secondary_url"]
