from __future__ import annotations

from http.server import ThreadingHTTPServer

from dtm_buildsheet.app.server import _APP_VERSION, _ReuseHTTPServer, _desktop_ui_url


def test_local_ui_server_handles_slow_requests_concurrently():
    """A slow provider request must not block the entire desktop UI."""
    assert issubclass(_ReuseHTTPServer, ThreadingHTTPServer)
    assert _ReuseHTTPServer.daemon_threads is True


def test_desktop_ui_url_changes_with_the_packaged_release():
    assert _desktop_ui_url(8765) == f"http://localhost:8765/?v={_APP_VERSION}"
