"""HTTP contract-snapshot harness (§8.1 Step 1b).

Freezes the request/response contract of route functions in ``app/routes/``
(GOLDEN_MASTER_SPEC.md's sibling pin — see AUDIT_REFACTOR_ROADMAP.md §3.1
"HTTP contract snapshots"). Route functions take ``(handler, method, path,
body, paths)`` and write JSON via ``send_json(handler, ...)``; this harness
drives them directly (no real socket, no ``BaseHTTPRequestHandler``
machinery) with a fake handler that captures the response, and reuses the
Step 1a hermetic-``AppPaths`` workspace so the snapshot is pinned against a
throwaway copy of the real seeded config, never the developer's live
workspace.

Two entry points:

    call_route(route_fn, method, full_path, body, paths) -> (status, json_body)
        full_path may include a query string; the dispatch path (what the
        route function's own `path` param expects) is the part before `?`,
        matching how app/server.py's do_GET/do_POST split them.

    canonical_dumps(data) -> str
        The one serialization used for stored snapshots and comparisons
        (sorted keys so cosmetic dict-ordering changes in route code can't
        produce a false diff; shared style with tests/golden/digest.py).
"""

from __future__ import annotations

import io
import json
from urllib.parse import urlparse

from tests.golden.harness import hermetic_paths  # reuse: same throwaway-AppPaths concept

__all__ = ["FakeHandler", "call_route", "canonical_dumps", "hermetic_paths"]


class FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler — captures what send_json writes."""

    def __init__(self, full_path: str):
        self.path = full_path  # route functions read handler.path for the query string
        self.status: int | None = None
        self.headers_sent: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, value))

    def end_headers(self) -> None:
        pass

    def body_json(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def call_route(route_fn, method: str, full_path: str, body: dict, paths):
    """Drive a route function the way app/server.py's dispatcher does.

    Returns (status, parsed_json_body, handled). ``handled`` mirrors the
    route function's own bool return (False means this path/method fell
    through to the caller's next candidate — a contract test asserting
    True is asserting the route still recognizes the path at all).
    """
    handler = FakeHandler(full_path)
    dispatch_path = urlparse(full_path).path
    handled = route_fn(handler, method, dispatch_path, body or {}, paths)
    return handler.status, (handler.body_json() if handler.status is not None else None), handled


def canonical_dumps(data) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
