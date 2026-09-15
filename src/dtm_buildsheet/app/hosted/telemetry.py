"""Fixed-schema stdout events. Never format request/provider messages or exceptions."""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time

_LOCK = threading.Lock()


def _emit(record):
    try:
        with _LOCK:
            print(json.dumps({"at": int(time.time()), **record}, separators=(",", ":")),
                  file=sys.stdout, flush=True)
    except (OSError, ValueError):
        # Observability failure must not repeat or change a business operation.
        pass


def request_event(path, method, request_id, status, elapsed):
    route = "unclassified"
    for name, pattern in (
        ("health", r"/healthz"), ("session", r"/api/hosted/session"),
        ("logout", r"/api/hosted/logout"), ("jobs", r"/api/hosted/jobs(?:/[0-9a-f]{64})?"),
        ("artifact", r"/api/hosted/artifacts/[0-9a-f]{48}"),
        ("document", r"/api/hosted/documents/[A-Za-z0-9_-]{1,80}"),
    ):
        if re.fullmatch(pattern, path):
            route = name
            break
    if route == "health" and status == 200:
        return
    _emit({"event": "http_request", "route": route,
           "method": method if method in {"GET", "POST", "PUT"} else "OTHER",
           "request_id": request_id if re.fullmatch(r"[0-9a-f]{32}", request_id) else "invalid",
           "status": int(status), "duration_ms": max(0, int(elapsed * 1000))})


class SafeLibraryHandler(logging.Handler):
    def emit(self, record):
        # Do not call getMessage/format: SDK URLs and exceptions can contain secrets.
        source = record.name.split(".", 1)[0]
        _emit({"event": "library_warning", "source": source if source in
               {"azure", "waitress", "urllib3", "jwt"} else "runtime",
               "severity": "error" if record.levelno >= logging.ERROR else "warning"})


def configure_logging():
    """Dedicated hosted process only. Desktop logging remains untouched."""
    root = logging.getLogger()
    root.handlers[:] = [SafeLibraryHandler()]
    root.setLevel(logging.WARNING)
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.handlers.clear()
            logger.propagate = True
            logger.setLevel(logging.NOTSET)


def lifecycle_event(event):
    if event not in {"starting", "startup_failed", "stopped"}:
        raise ValueError("Unknown lifecycle event")
    _emit({"event": event})
