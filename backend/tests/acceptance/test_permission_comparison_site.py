"""Black-box tests for the loopback-only permission acceptance site."""

from __future__ import annotations

from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener, urlopen

import pytest

from ai_ui_explorer.acceptance.permission_comparison_site import (
    PermissionAcceptanceSite,
)


def test_site_binds_loopback_and_rejects_unknown_login_role() -> None:
    """A caller cannot obtain a role cookie using an unrecognised query value."""
    with PermissionAcceptanceSite(port=0) as site:
        assert site.origin.startswith("http://127.0.0.1:")
        with pytest.raises(HTTPError) as error:
            urlopen(f"{site.origin}/login-complete?role=unknown")

    assert error.value.code == 400
    assert error.value.headers.get("Set-Cookie") is None


def test_admin_login_exposes_fixture_admin_navigation() -> None:
    """Only the fixed admin role reaches the dashboard with its fixture link."""
    with PermissionAcceptanceSite(port=0) as site:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        opener.open(f"{site.origin}/login-complete?role=admin")
        dashboard = opener.open(site.dashboard_url).read()

    assert b"/admin.html" in dashboard
