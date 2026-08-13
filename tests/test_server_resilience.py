from __future__ import annotations

from http.server import ThreadingHTTPServer

from dtm_buildsheet.app.server import _ReuseHTTPServer


def test_local_ui_server_handles_slow_requests_concurrently():
    """A slow provider request must not block the entire desktop UI."""
    assert issubclass(_ReuseHTTPServer, ThreadingHTTPServer)
    assert _ReuseHTTPServer.daemon_threads is True
