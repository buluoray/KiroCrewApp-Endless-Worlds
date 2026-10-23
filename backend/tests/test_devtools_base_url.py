"""The harness must address the gateway on the host it will not be redirected from.

The gateway 302s a credential-less top-level page load on any loopback alias onto
its canonical host. The driver signs in once with `?token=` and then opens the app
page without it, so if the harness's base URL is not the canonical host, that load
moves to a host the session cookie was never set on, and every shot photographs the
"session expired" page. Checked against the gateway's OWN redirect rule, so a change
of canonical host breaks this test instead of the UI shots job.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "devtools"))

import instance  # noqa: E402

urls = pytest.importorskip("kiro_crew.dashboard.urls")


def test_app_page_load_stays_on_the_host_that_holds_the_session_cookie(tmp_path):
    got = instance.Instance(tmp_path, 41234, "tok", 1)
    host = urlsplit(got.base_url).netloc
    canonical = urls.resolve_dashboard_host(True)
    assert not urls.should_canonicalize_host(
        host, canonical, method="GET", sec_fetch_dest="document"
    ), f"{got.base_url}/apps/... would be redirected to {canonical}, off the session cookie"
